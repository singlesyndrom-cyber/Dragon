import type { MetadataRoute } from "next";

/** «Добавить на главный экран» на телефоне: название и иконки клуба. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Dragon — турниры клубов ККИ",
    short_name: "Dragon",
    start_url: "/",
    display: "standalone",
    background_color: "#000000",
    theme_color: "#141826",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
