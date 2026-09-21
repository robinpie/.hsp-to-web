(Read `READ ME.hsp`, rendered at https://dreamstation.systems/hsptohtml/README/pages/README.html, for the proper readme.)

I'm not done working on this.

Accessibility works now. Every page carries its text as real text in the DOM (the pixels are painted over it with CSS masks instead of blitted into a canvas), links are `<a href>`, images have alt text, and every page has a plain-HTML text view. There are also controls.

OpenGraph embeds are in too. Pass `--base-url` to `build.sh` or `hsppack.py` if you want `og:url` and `og:image` filled in as absolute URLs.
