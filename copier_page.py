"""
Script pour visiter une page web et en récupérer le contenu exact.

Méthodes proposées :
1. rapide()          -> récupère le texte de la page directement (rapide, sans navigateur visible)
2. avec_ctrl_a()      -> ouvre un vrai navigateur, sélectionne tout (Ctrl+A) et lit la sélection
                         (équivalent Ctrl+C), sans passer par le presse-papier
3. capture_ecran()    -> prend une capture d'écran de la page entière (comme une vraie photo)

Installation nécessaire :
    pip install requests beautifulsoup4 selenium --break-system-packages

Il faut aussi Chrome installé (chromedriver est géré automatiquement par selenium >= 4.6).
"""

import time


# ---------------------------------------------------------------------------
# MÉTHODE 1 : récupération directe du contenu (recommandée, la plus rapide)
# ---------------------------------------------------------------------------
def rapide(url: str) -> str:
    """Récupère le texte visible de la page directement, sans navigateur."""
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ScriptPython/1.0)"}
    reponse = requests.get(url, headers=headers, timeout=10)
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    return soup.get_text(separator="\n", strip=True)


# ---------------------------------------------------------------------------
# Utilitaires communs (navigateur + attente de chargement)
# ---------------------------------------------------------------------------
def _creer_navigateur(headless: bool = True):
    """Crée un navigateur Chrome configuré pour éviter la détection anti-bot
    (CloudFront, Cloudflare, etc. bloquent souvent les navigateurs automatisés
    par défaut avec une erreur 403)."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
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
    """Cherche et clique automatiquement sur un bouton d'acceptation de cookies
    (OneTrust, Cookiebot, bannières maison, etc.). Ne fait rien si aucun bouton
    n'est trouvé — certains sites conditionnent le chargement de widgets/listes
    de contenu à l'acceptation des cookies, d'où l'intérêt de le faire tôt."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    selecteurs = [
        (By.ID, "onetrust-accept-btn-handler"),  # très répandu (OneTrust)
        (By.XPATH, "//button[contains(translate(text(), 'ACEPT', 'acept'), 'accept')]"),
        (By.XPATH, "//button[contains(., 'Accept Cookies')]"),
        (By.XPATH, "//button[contains(., 'Tout accepter')]"),
        (By.XPATH, "//button[contains(., 'J\\'accepte')]"),
    ]
    for by, valeur in selecteurs:
        try:
            bouton = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, valeur))
            )
            bouton.click()
            time.sleep(1)  # laisse le temps aux widgets dépendants de se recharger
            return True
        except Exception:
            continue
    return False


def _masquer_publicites(driver):
    """Masque les bannières publicitaires/promo qui flottent par-dessus le
    contenu (bandeaux sticky, pop-ins 'Get X Today', etc.), pour qu'elles
    n'apparaissent pas sur les captures ni ne polluent le texte extrait.
    Ne supprime rien de la mise en page normale (header/footer collés en
    haut/bas de l'écran ne sont pas touchés)."""
    script = """
        const motsCles = ['ad-banner','advertisement','sticky-ad','ad-container',
                           'adsbygoogle','taboola','outbrain','criteo','mediavine',
                           'adthrive','grow-me','grow-banner','growjs','grow-widget',
                           'grow-sticky','grow-unit','grow-native','promo-banner',
                           'sticky-promo','ad-slot','ad-wrapper'];

        function masquer(el) {
            el.style.setProperty('display', 'none', 'important');
        }

        // Masque l'élément ET remonte jusqu'à 3 niveaux de parents pour
        // couvrir le conteneur (fond, bordure) qui porte le vrai fond visuel
        // de la bannière, pas seulement le texte/logo à l'intérieur.
        function masquerAvecParents(el, niveaux) {
            let courant = el;
            for (let i = 0; i <= niveaux && courant && courant.tagName !== 'BODY'; i++) {
                masquer(courant);
                courant = courant.parentElement;
            }
        }

        document.querySelectorAll('*').forEach(el => {
            const idClasse = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
            if (typeof idClasse !== 'string') return;
            const contientGrowSeul = /(^|[^a-z])grow([^a-z]|$)/.test(idClasse) && !idClasse.includes('growth');
            if (motsCles.some(m => idClasse.includes(m)) || contientGrowSeul) {
                masquerAvecParents(el, 3);
            }
        });

        // Filet de sécurité générique : tout élément flottant (fixed/sticky),
        // à z-index élevé, qui n'est PAS collé en haut ou en bas de l'écran
        // (donc pas un header/footer normal) est presque toujours une pub
        // ou un pop-in promotionnel qui recouvre le contenu.
        document.querySelectorAll('*').forEach(el => {
            const style = window.getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                const z = parseInt(style.zIndex) || 0;
                const rect = el.getBoundingClientRect();
                const collePresDuBord = rect.top < 5 || (window.innerHeight - rect.bottom) < 5;
                const tailleRaisonnable = rect.height > 20 && rect.height < window.innerHeight * 0.5;
                if (z > 100 && !collePresDuBord && tailleRaisonnable) {
                    masquer(el);
                }
            }
        });
    """
    try:
        driver.execute_script(script)
    except Exception:
        pass


def _masquer_publicites_avec_attente(driver, essais=3, delai=1.5):
    """Répète le nettoyage des pubs plusieurs fois avec un délai entre chaque
    passage, car certaines bannières (widgets tiers type 'Grow') se chargent
    en différé, après que la page soit déjà considérée comme stable."""
    for _ in range(essais):
        _masquer_publicites(driver)
        time.sleep(delai)
    _masquer_publicites(driver)  # dernier nettoyage juste avant utilisation


def _attendre_page_stable(driver, timeout=20, pause=0.5, stabilite=1.0):
    """Attend que la page soit chargée ET que le contenu arrête de bouger
    (utile pour les sites qui chargent des données en JS après coup)."""
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


# ---------------------------------------------------------------------------
# MÉTHODE 2 : simulation réelle de Ctrl+A / Ctrl+C via un navigateur
# ---------------------------------------------------------------------------
def avec_ctrl_a(url: str, headless: bool = True, timeout: int = 20) -> str:
    """Ouvre un navigateur, va sur l'URL, attend que la page soit stable,
    sélectionne tout le contenu (équivalent Ctrl+A) et retourne le texte
    sélectionné via JavaScript (équivalent Ctrl+C)."""
    driver = _creer_navigateur(headless)
    try:
        driver.get(url)
        _accepter_cookies(driver)
        _attendre_page_stable(driver, timeout=timeout)
        _masquer_publicites_avec_attente(driver)

        script_selection = """
            var sel = window.getSelection();
            sel.removeAllRanges();
            var range = document.createRange();
            range.selectNodeContents(document.body);
            sel.addRange(range);
            return sel.toString();
        """
        return driver.execute_script(script_selection)
    finally:
        driver.quit()


# ---------------------------------------------------------------------------
# MÉTHODE 3 : capture d'écran de la page entière
# ---------------------------------------------------------------------------
def capture_ecran(url: str, fichier: str = "capture.png", headless: bool = True,
                   timeout: int = 20, page_entiere: bool = True) -> str:
    """Ouvre un navigateur, va sur l'URL, attend que la page soit stable,
    et sauvegarde une capture d'écran (PNG).

    page_entiere=True : capture toute la hauteur de la page via le protocole
                         natif de Chrome (CDP), sans redimensionner la fenêtre
                         (le redimensionnement déclenche parfois une réorganisation
                         de la page qui donne un rendu dupliqué/incomplet).
    """
    import base64

    driver = _creer_navigateur(headless)
    try:
        driver.get(url)
        _accepter_cookies(driver)
        _attendre_page_stable(driver, timeout=timeout)
        _masquer_publicites_avec_attente(driver)

        if page_entiere:
            # Mesure la taille réelle du document rendu, sans y toucher.
            metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
            content_size = metrics["cssContentSize"]

            resultat = driver.execute_cdp_cmd("Page.captureScreenshot", {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {
                    "x": 0,
                    "y": 0,
                    "width": content_size["width"],
                    "height": content_size["height"],
                    "scale": 1,
                },
            })
        else:
            # Capture uniquement ce qui est visible à l'écran.
            resultat = driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png"})

        with open(fichier, "wb") as f:
            f.write(base64.b64decode(resultat["data"]))

        return fichier
    finally:
        driver.quit()


# ---------------------------------------------------------------------------
# MÉTHODE 4 : extraire un tableau HTML de la page et l'exporter en Excel
# ---------------------------------------------------------------------------
def tableau_vers_excel(url: str, fichier: str = "tableau.xlsx", headless: bool = True,
                        timeout: int = 20, index_tableau: int = 0) -> str:
    """Ouvre un navigateur, va sur l'URL, attend que la page soit stable,
    et extrait un tableau HTML (<table>) avec les valeurs EXACTES affichées
    (pas de l'OCR sur une image, donc aucun risque d'erreur de lecture).

    index_tableau : si la page contient plusieurs <table>, choisit lequel
                    exporter (0 = le premier trouvé sur la page).
    """
    from selenium.webdriver.common.by import By
    import pandas as pd

    driver = _creer_navigateur(headless)
    try:
        driver.get(url)
        _accepter_cookies(driver)
        _attendre_page_stable(driver, timeout=timeout)
        _masquer_publicites_avec_attente(driver)

        tables = driver.find_elements(By.TAG_NAME, "table")
        if not tables:
            raise ValueError("Aucun tableau <table> trouvé sur cette page.")
        table = tables[index_tableau]

        lignes = table.find_elements(By.TAG_NAME, "tr")
        donnees = []
        for ligne in lignes:
            cellules = ligne.find_elements(By.XPATH, "./th|./td")
            donnees.append([c.text.strip() for c in cellules])

        # Filtre les lignes vides éventuelles
        donnees = [l for l in donnees if any(l)]
        entetes, *lignes_donnees = donnees

        df = pd.DataFrame(lignes_donnees, columns=entetes)
        df.to_excel(fichier, index=False)
        return fichier
    finally:
        driver.quit()


if __name__ == "__main__":
    # Ajoute ou retire des URLs dans cette liste selon tes besoins
    urls = [
        "https://rateprobability.com/",
        "https://rateprobability.com/fed",
        "https://rateprobability.com/boc",
        "https://rateprobability.com/ecb",
        "https://rateprobability.com/boe",
        "https://rateprobability.com/boj",
        "https://rateprobability.com/rba",
    ]

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{len(urls)}] Visite de {url} ...")
        nom_fichier = url.split("//")[-1].strip("/").replace("/", "_").replace(".", "_")
        if not nom_fichier:
            nom_fichier = "accueil"

        try:
            fichier_image = capture_ecran(url, fichier=f"capture_{nom_fichier}.png")
            print(f"    image sauvegardée dans {fichier_image}")
        except Exception as e:
            print(f"    échec capture image pour {url} : {e}")

        try:
            fichier_excel = tableau_vers_excel(url, fichier=f"tableau_{nom_fichier}.xlsx")
            print(f"    tableau exporté dans {fichier_excel}")
        except Exception as e:
            print(f"    échec export Excel pour {url} : {e}")
