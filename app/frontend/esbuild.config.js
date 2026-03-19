import esbuild from "esbuild";

const watch = process.argv.includes("--watch");

/** @type {esbuild.BuildOptions} */
const config = {
  entryPoints: ["src/app.jsx"],
  bundle: true,
  outdir: "../static/js",
  format: "esm",
  target: "es2020",
  jsx: "automatic",
  jsxImportSource: "preact",
  alias: {
    // Prevent dual-Preact hazard when superhot-ui has its own node_modules/preact
    react: "preact/compat",
    "react-dom": "preact/compat",
  },
  sourcemap: watch,
  minify: !watch,
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(config);
  await ctx.watch();
  console.log("Watching...");
} else {
  await esbuild.build(config);
}
