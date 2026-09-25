const menuToggle = document.querySelector(".menu-toggle");
const primaryNavigation = document.querySelector("#primary-navigation");

if (menuToggle && primaryNavigation) {
    const mobileScreen = window.matchMedia("(max-width: 600px)");

    function setMenuOpen(isOpen) {
        menuToggle.setAttribute("aria-expanded", String(isOpen));
        primaryNavigation.hidden = !isOpen;
    }

    function updateNavigation() {
        const isMobile = mobileScreen.matches;
        const focusWasInside = primaryNavigation.contains(
            document.activeElement
        );
        const toggleHadFocus = document.activeElement === menuToggle;

        menuToggle.hidden = !isMobile;
        setMenuOpen(!isMobile);

        if (isMobile && focusWasInside) {
            menuToggle.focus();
        } else if (!isMobile && toggleHadFocus) {
            primaryNavigation.querySelector("a")?.focus();
        }
    }

    menuToggle.addEventListener("click", () => {
        const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
        setMenuOpen(!isOpen);
    });

    document.addEventListener("keydown", (event) => {
        if (
            event.key === "Escape" &&
            mobileScreen.matches &&
            menuToggle.getAttribute("aria-expanded") === "true"
        ) {
            setMenuOpen(false);
            menuToggle.focus();
        }
    });

    mobileScreen.addEventListener("change", updateNavigation);
    updateNavigation();
}