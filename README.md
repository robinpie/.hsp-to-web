(Read `READ ME.hsp`, rendered at https://dreamstation.systems/hsptohtml/README/pages/README.html, for the proper readme.)

I'm not done working on this.

Accessibility works now. Every page carries its text as real text in the DOM (the pixels are painted over it with CSS masks, not blitted into a canvas), links are `<a href>`, images have alt text, and every page has a plain-HTML text view that reflows and takes your own font size — the "Text view" button, the `t` key, or `#text` on the URL. Music and motion have visible controls and honour `prefers-reduced-motion`. `tools/hspaudit.py` reports what is left, including which pages fail contrast — which is a thing about 1999, not about the converter, and is what the text view is there for.

OpenGraph embeds are in too. Pass `--base-url` to `build.sh` or `hsppack.py` if you want `og:url` and `og:image` filled in as absolute URLs.
