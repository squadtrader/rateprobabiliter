# -*- coding: utf-8 -*-
"""
test_rateprobability.py - Test d'extraction isole, SANS Firestore.

But : verifier que les regex de rateprobability_cloud.py trouvent bien
les bonnes valeurs sur le vrai DOM, avant de brancher quoi que ce soit
sur Firestore/le cron. N'ecrit rien nulle part a part une capture .png
et les logs dans la console.

Usage :
    pip install selenium beautifulsoup4 --break-system-packages
    python test_rateprobability.py
"""

import re
import time
import base64
import os

from bs4 import BeautifulSoup

URL_TEST = "https://rateprobability.com/fed"


def _creer_navigateur():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
    )
    return driver


def _accepter_cookies(driver, timeout=5):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    selecteurs = [
        (By.ID, "onetrust-accept-btn-handler"),
        (By.XPATH, "//button[contains(translate(text(), 'ACEPT', 'acept'), 'accept')]"),
    ]
    for by, valeur in selecteurs:
        try:
            bouton = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, valeur)))
            bouton.click()
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def _attendre_page_stable(driver, timeout=20, pause=0.5, stabilite=1.0):
    fin = time.time() + timeout
    derniere_taille = -1
    stable_depuis = time.time()

    while time.time() < fin:
        if driver.execute_script("return document.readyState") == "complete":
            break
        time.sleep(0.2)

    while time.time() < fin:
        taille_actuelle = len(driver.execute_script("return document.body.innerText"))
        if taille_actuelle == derniere_taille:
            if time.time() - stable_depuis >= stabilite:
                return
        else:
            derniere_taille = taille_actuelle
            stable_depuis = time.time()
        time.sleep(pause)


def _valeur_apres_label(texte, label, motif_valeur, fenetre=120):
    m_label = re.search(re.escape(label), texte, re.IGNORECASE)
    if not m_label:
        return None
    zone = texte[m_label.end():m_label.end() + fenetre]
    m_valeur = re.search(motif_valeur, zone, re.IGNORECASE | re.DOTALL)
    return m_valeur.group(1).strip() if m_valeur else None


def extraire_tableau_meetings(driver):
    soup = BeautifulSoup(driver.page_source, "html.parser")
    table_cible = None
    for table in soup.find_all("table"):
        entete = table.find("tr")
        if not entete:
            continue
        texte_entete = entete.get_text(" ", strip=True).lower()
        if "meeting" in texte_entete and "implied" in texte_entete:
            table_cible = table
            break

    if table_cible is None:
        return []

    lignes = table_cible.find_all("tr")
    resultats = []
    for ligne in lignes[1:]:
        cellules = ligne.find_all(["td", "th"])
        if len(cellules) < 4:
            continue
        valeurs = [c.get_text(strip=True) for c in cellules]
        resultats.append({
            "meeting": valeurs[0] if len(valeurs) > 0 else "",
            "taux_implique": valeurs[1] if len(valeurs) > 1 else "",
            "probabilite": valeurs[2] if len(valeurs) > 2 else "",
            "nb_hikes_cuts": valeurs[3] if len(valeurs) > 3 else "",
            "delta_vs_actuel_bps": valeurs[4] if len(valeurs) > 4 else "",
        })
    return resultats


def main():
    print(f"Ouverture de {URL_TEST} ...")
    driver = _creer_navigateur()
    try:
        driver.get(URL_TEST)
        _accepter_cookies(driver)
        _attendre_page_stable(driver, timeout=20)

        # --- 1. Texte brut de la page, pour inspection manuelle ---
        texte = driver.execute_script("return document.body.innerText")
        with open("texte_page_brut.txt", "w", encoding="utf-8") as f:
            f.write(texte)
        print("Texte brut de la page sauvegardé dans texte_page_brut.txt (pour vérification manuelle)")

        # --- 2. Capture d'écran, pour comparaison visuelle ---
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        content_size = metrics["cssContentSize"]
        resultat = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": content_size["width"], "height": content_size["height"], "scale": 1},
        })
        with open("test_capture.png", "wb") as f:
            f.write(base64.b64decode(resultat["data"]))
        print("Capture sauvegardée dans test_capture.png")

        # --- 3. Extraction des champs, un par un, avec affichage clair ---
        print("\n" + "=" * 60)
        print("CHAMPS EXTRAITS :")
        print("=" * 60)

        champs = {
            "taux_actuel": _valeur_apres_label(texte, "Current Rate", r"([\d.]+%)"),
            "as_of_texte": _valeur_apres_label(texte, "As of:", r"([\d:]{3,5}\s+[\d/]{6,10})"),
            "target_band": _valeur_apres_label(texte, "Target Band:", r"([\d.]+[\-–][\d.]+%)"),
            "prochaine_decision_date": _valeur_apres_label(
                texte, "Next decision in", r"\n\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}[^\n]*)", fenetre=200
            ),
            "prochaine_decision_pricing": _valeur_apres_label(
                texte, "Next meeting pricing", r"(\d+%\s*(?:HIKE|CUT|HOLD))"
            ),
            "prochaine_decision_bps": _valeur_apres_label(
                texte, "Next meeting pricing", r"HIKE|CUT|HOLD\)?\s*\n?\s*([+\-][\d.]+\s*bps)", fenetre=60
            ),
            "outlook_12m_bps": _valeur_apres_label(texte, "12-Month", r"([+\-][\d.]+\s*bps)"),
            "outlook_12m_texte": _valeur_apres_label(
                texte, "12-Month", r"(\d+\s*(?:or\s*\d+\s*)?(?:hikes?|cuts?))"
            ),
        }

        for nom_champ, valeur in champs.items():
            statut = "OK" if valeur else "MANQUANT"
            print(f"  [{statut:9}] {nom_champ:30} = {valeur!r}")

        tableau = extraire_tableau_meetings(driver)
        print(f"\n  [{'OK' if tableau else 'MANQUANT':9}] tableau_meetings ({len(tableau)} ligne(s))")
        for ligne in tableau[:3]:
            print(f"      {ligne}")
        if len(tableau) > 3:
            print(f"      ... et {len(tableau) - 3} autre(s) ligne(s)")

        print("\n" + "=" * 60)
        print("Vérifie texte_page_brut.txt pour ajuster les regex si des champs sont MANQUANT.")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
