import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const siteUrl = (env.VITE_SITE_URL || "http://localhost:5173").replace(/\/$/, "");
  const outDir = env.VITE_OUT_DIR || "dist";

  return {
    plugins: [
      {
        name: "site-url-html-placeholder",
        transformIndexHtml: {
          order: "pre",
          handler(html) {
            return html.replaceAll("%VITE_SITE_URL%", siteUrl);
          },
        },
      },
      {
        name: "build-seo-assets",
        apply: "build",
        closeBundle() {
          const distDir = resolve(process.cwd(), outDir);
          mkdirSync(distDir, { recursive: true });
          try {
            writeFileSync(
              resolve(distDir, "robots.txt"),
              `User-agent: *\nAllow: /\n\nSitemap: ${siteUrl}/sitemap.xml\n`,
              "utf8",
            );
            writeFileSync(
              resolve(distDir, "sitemap.xml"),
              `<?xml version="1.0" encoding="UTF-8"?>\n` +
                `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
                `  <url>\n` +
                `    <loc>${siteUrl}/</loc>\n` +
                `    <lastmod>2026-07-08</lastmod>\n` +
                `    <changefreq>weekly</changefreq>\n` +
                `    <priority>1.0</priority>\n` +
                `  </url>\n` +
                `  <url>\n` +
                `    <loc>${siteUrl}/llms.txt</loc>\n` +
                `    <lastmod>2026-07-08</lastmod>\n` +
                `    <changefreq>monthly</changefreq>\n` +
                `    <priority>0.6</priority>\n` +
                `  </url>\n` +
                `</urlset>\n`,
              "utf8",
            );
          } catch (error) {
            console.warn("SEO asset generation skipped:", error);
          }
        },
      },
      vue(),
      tailwindcss(),
    ],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
        "/uploads": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir,
    },
  };
});
