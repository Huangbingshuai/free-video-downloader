import { createApp } from "vue";
import App from "./App.vue";
import { syncSeoUrls } from "./seo";
import "./styles.css";

syncSeoUrls();
createApp(App).mount("#app");
