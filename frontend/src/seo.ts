function setMeta(selector: string, content: string) {
  const element = document.head.querySelector<HTMLMetaElement>(selector);
  if (element) element.content = content;
}

function setLink(selector: string, href: string) {
  const element = document.head.querySelector<HTMLLinkElement>(selector);
  if (element) element.href = href;
}

export function syncSeoUrls() {
  const homeUrl = new URL("/", window.location.origin).href;
  const imageUrl = new URL("/og-cover.svg", window.location.origin).href;

  setLink('link[rel="canonical"]', homeUrl);
  setLink('link[rel="alternate"][hreflang="zh-CN"]', homeUrl);
  setLink('link[rel="alternate"][hreflang="x-default"]', homeUrl);
  setMeta('meta[property="og:url"]', homeUrl);
  setMeta('meta[property="og:image"]', imageUrl);
  setMeta('meta[name="twitter:image"]', imageUrl);
  setMeta('meta[itemprop="image"]', imageUrl);
}

