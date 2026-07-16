#!/bin/sh
# Rebuild the self-contained demo from the canonical JSX.
# Requires: npm i esbuild react@18 react-dom@18 three@0.147.0 (one directory up or here)
npx esbuild entry.jsx --bundle --loader:.jsx=jsx --jsx=automatic --format=iife --minify \
  --define:process.env.NODE_ENV='"production"' --outfile=/tmp/tp_bundle.js
python3 - << 'PY'
bundle = open("/tmp/tp_bundle.js").read()
html = open("thirdpersona_demo.html").read()
start = html.index("<script>") + 8; end = html.rindex("</script>")
open("thirdpersona_demo.html", "w").write(html[:start] + "\n" + bundle + "\n" + html[end:])
print("demo rebuilt")
PY
