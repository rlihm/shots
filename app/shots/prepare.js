// Runs in the page before every screenshot.
// __HIDE__ is replaced by capture.py with the combined list of selectors to hide.
new Promise(async (resolve) => {
  const hide = __HIDE__;

  // 1. Hide cookie banners, chat widgets and anything else listed in the config
  //    and stop animations and transitions
  const style = document.createElement("style");
  style.textContent = `
    ${hide.length ? hide.join(",\n") + " { display: none !important; visibility: hidden !important; }" : ""}
    *, *::before, *::after {
      animation-duration: 0s !important; animation-delay: 0s !important;
      transition: none !important; caret-color: transparent !important;
    }
    html, body { overflow: auto !important; }  /* banners often lock scrolling */
  `;
  document.head.appendChild(style);

  // 1b. Catch unknown or custom-built banners by behaviour rather than by name:
  //     - floating (fixed/absolute) elements whose text mentions cookies or consent
  //     - fixed full-screen overlays (the dark backdrop behind a consent dialog)
  const CONSENT = /cookie|consent|einwilligung|zustimm|tracking/i;
  const hideOverlays = () => {
    const vw = window.innerWidth, vh = window.innerHeight;
    for (const el of document.querySelectorAll("body *")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none") continue;
      const fixed = cs.position === "fixed";
      const floating = cs.position === "absolute" && parseInt(cs.zIndex || 0, 10) >= 100;
      if (!fixed && !floating) continue;
      const r = el.getBoundingClientRect();
      const text = (el.innerText || "").slice(0, 4000);
      const isConsent = CONSENT.test(text) && text.length < 4000
        && !el.querySelector("header, nav, main, article");
      const isBackdrop = fixed && r.width >= vw * 0.9 && r.height >= vh * 0.9
        && text.trim().length < 200;
      if (isConsent || isBackdrop) el.style.setProperty("display", "none", "important");
    }
  };
  hideOverlays();

  // 2. Scroll down step by step so lazy-loaded images and sections load, then go back up
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const step = Math.max(window.innerHeight * 0.8, 400);
  for (let y = 0; y < document.body.scrollHeight && y < 30000; y += step) {
    window.scrollTo(0, y);
    await sleep(150);
  }
  window.scrollTo(0, 0);

  // 3. Force native lazy images to load, then wait for images and web fonts
  document.querySelectorAll('img[loading="lazy"]').forEach((img) => (img.loading = "eager"));
  const pending = [...document.images]
    .filter((img) => !img.complete)
    .map((img) => new Promise((r) => { img.onload = img.onerror = r; }));
  await Promise.race([Promise.all(pending), sleep(5000)]);
  if (document.fonts) await document.fonts.ready;

  hideOverlays(); // again, for banners that appear with a delay or on scroll
  await sleep(500); // let sticky headers settle after scrolling back up
  resolve(true);
});
