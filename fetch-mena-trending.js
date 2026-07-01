const { chromium } = require("playwright");

(async () => {
  const ua =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
  const browser = await chromium.launch({
    headless: true,
    args: ["--disable-blink-features=AutomationControlled"],
  });
  const context = await browser.newContext({
    userAgent: ua,
    locale: "ar-EG",
    timezoneId: "Africa/Cairo",
    viewport: { width: 1440, height: 1200 },
    extraHTTPHeaders: {
      "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    },
  });

  const page = await context.newPage();
  await page.goto("https://www.wheretowatch.stream/?language=ar-EG&country=eg", {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForTimeout(1500);
  console.log("start", page.url());

  const result = await page.evaluate(async () => {
    const fp = {
      screen: `${screen.width}x${screen.height}x${screen.colorDepth}`,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      language: navigator.language,
      platform: navigator.platform,
      cookieEnabled: navigator.cookieEnabled,
      plugins: Array.from(navigator.plugins).map((p) => p.name),
    };
    const getCookie = (name) => {
      const value = `; ${document.cookie}`;
      const parts = value.split(`; ${name}=`);
      return parts.length === 2 ? parts.pop().split(";").shift() : null;
    };

    const nonceRes = await fetch("/api/request-nonce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fingerprint: fp,
        isMobile: false,
        userAgent: navigator.userAgent,
        timestamp: Date.now(),
      }),
    });
    const nonceJson = await nonceRes.json();
    await new Promise((resolve) => setTimeout(resolve, 500));
    const nonce = getCookie("__js_nonce");

    const jsRes = await fetch("/api/js-verified", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nonce,
        path: location.href,
        timestamp: Date.now(),
        attempt: 0,
        userAgent: navigator.userAgent,
        fingerprint: fp,
        isMobile: false,
        isAutoVerify: false,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        screen: `${screen.width}x${screen.height}`,
        language: navigator.language,
        referrer: document.referrer,
        behavioralData: {
          pageLoadTime: performance.now(),
          focusEvents: document.hasFocus(),
          scrollBehavior: window.scrollY,
          clickPattern: "manual",
        },
      }),
    });
    const jsText = await jsRes.text();
    let botText = "";
    if (jsRes.ok) {
      const botRes = await fetch("/api/bot-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signals: ["manual-click", "normal-headers", "ar-eg"] }),
      });
      botText = await botRes.text();
    }

    return {
      nonceJson,
      noncePresent: Boolean(nonce),
      jsStatus: jsRes.status,
      jsText,
      botText,
      cookie: document.cookie,
    };
  });
  console.log("challengeResult", JSON.stringify(result, null, 2));

  await page.goto("https://www.wheretowatch.stream/?language=ar-EG&country=eg", {
    waitUntil: "networkidle",
    timeout: 60000,
  });
  await page.waitForTimeout(7000);
  console.log("final", page.url(), await page.title());
  console.log("body", JSON.stringify((await page.locator("body").innerText()).slice(0, 3000)));

  const data = await page.evaluate(() => {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const text = (el) => norm(el.innerText);
    const sections = [...document.querySelectorAll("section,[role=region],main > div,div")]
      .filter((el) =>
        /MENA|mena|ترند|رائج|الأكثر|الأعلى|الشرق الأوسط|شمال أفريقيا|مصر|مسلسلات|تركية|Trending/i.test(
          text(el)
        )
      )
      .slice(0, 60)
      .map((el, i) => ({
        i,
        tag: el.tagName,
        id: el.id,
        cls: String(el.className),
        text: text(el).slice(0, 4000),
        html: el.outerHTML.slice(0, 6000),
      }));
    const cards = [...document.querySelectorAll("a")]
      .map((a) => ({
        text: text(a),
        href: a.href,
        img: a.querySelector("img")?.src || "",
        alt: a.querySelector("img")?.alt || "",
        aria: a.getAttribute("aria-label") || "",
      }))
      .filter(
        (x) =>
          x.href &&
          /\/shows\/|\/movies\/|tmdb|image|poster|مسلسل|تركية|أخي|حب|البحر|شراب|ورود|أشرف|orhan|far|love|envy|trend|mena|صمود|شعلة|محمد|أيلاماز|عائشة|جبل/i.test(
            JSON.stringify(x)
          )
      )
      .slice(0, 500);
    return { sections, cards };
  });
  console.log("DOMDATA=" + JSON.stringify(data, null, 2));

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
