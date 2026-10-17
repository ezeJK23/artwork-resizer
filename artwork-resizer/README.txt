ARTWORK RESIZER
===============

Start
  Double-click "Start Artwork Resizer.command".
  The app opens in your browser at http://localhost:8765.
  Leave the small Terminal window open while you work; close it to stop the app.
  (First time only: if macOS says the file is from an unidentified developer,
   right-click it > Open > Open.)

Use
  1. Choose where it will be shown (Guerlain stores / Other stores) and the language.
  2. Enter the finished size (mm, cm, inches or pixels) and the bleed.
  3. The proof updates instantly with the layout the master guide defines for that ratio.
     Tick "Guide reference" to see the guide's own layout beside it,
     and "Element boxes" to see how each text/logo block is pinned.
  4. Click "Create artwork (.ai)". Files are saved in the Output folder.
  Batch: open "Batch: several sizes at once" and enter one size per line.

How the layout is decided
  * The guide gives one layout per ratio range (e.g. 0.71 - 0.91).
  * At the guide's own ratio the result is identical to the guide.
  * Between, the same layout is scaled to the new size: blocks near an edge stay pinned
    to that edge (logo at the top, legal lines at the bottom); claims beside the product
    move with the picture, so they stay next to the bottles.
  * The picture is framed from the full link image around the guide's framing.
  * Sizes outside 0.16 - 4.10 are flagged: the guide does not cover them.

Files
  * .ai files are vector PDFs: they open and edit in Illustrator and Acrobat.
    Text stays live (Guerlain Sans embedded), logos stay vector, colours are copied
    untouched (CMYK pictures stay CMYK).
  * Layers: Background, then one layer per text/logo block (visible in Acrobat's Layers panel).
  * Trim and bleed boxes are set for print.

Current limits
  * The project uses the LOW-RES links (Lowres_Links). The app shows the picture
    resolution for each size and warns below 250 ppi. High-res links must be added
    before final print output.
