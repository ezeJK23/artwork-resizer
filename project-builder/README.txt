PROJECT BUILDER
===============
Turns a master layout guide (PDF) into a project for Artwork Resizer.

Start
  Double-click "Start Project Builder.command". It opens at http://localhost:8766.
  The first start installs the image tools it needs (one time, needs internet, 1-3 minutes).
  Keep the Terminal window open while you work.

Create a project
  1. Type a project name.
  2. Drag the master guide PDF onto "Master guide PDF".
  3. Optional: drag the Links folder (or the picture files) onto "Link pictures".
     With links, the picture can be reframed beyond the guide's crop and keeps full link resolution.
     Without links, the guide's own picture is used (cropping only).
  4. Click "Build project". When it finishes, open Artwork Resizer and pick the project
     from the Project menu (reload the page if it was already open).

What the guide needs
  * Pages with a "Ratio" label: either one ratio ("Ratio: 0.75") or a range
    ("Ratio: 0.71 -> 0.91").
  * The artwork drawn on the page as a placed picture with the logo / text / product on top.
  * Several versions on one page are supported; they are named from labels such as "VERSION FR".

Where projects go
  Into "Artwork Resizer/projects" when the two app folders sit side by side,
  otherwise into a "projects" folder here.
