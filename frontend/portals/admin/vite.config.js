import { defineConfig } from "vite";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
const require=createRequire(import.meta.url);const root=path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({root,resolve:{alias:{react:require.resolve("react"),"react-dom":require.resolve("react-dom")}},build:{outDir:"dist",emptyOutDir:true},server:{host:"0.0.0.0"}});
