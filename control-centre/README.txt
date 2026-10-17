CONTROL CENTRE  (vendor tool – keep private)
==============
One place to manage everything. Double-click "Start Control Centre.command"
(opens http://localhost:8770). "Start License Manager.command" opens the same thing.

  Overview          licences at a glance, renewals due, apps running on this Mac
  Licences          issue, renew, copy and check licence codes          (back end)
  Apps & files      start / stop / open Artwork Resizer and Project Builder,
                    see the artwork files they created                  (front end)
  Users             add users, set new passwords, change roles, remove  (front end)
  Projects          see, rename or remove projects; start a new one     (front end)
  This Mac's licence  see or enter the licence the apps use on this Mac (front end)
  Password & folders  change the manager password, open folders

The Control Centre expects the "Artwork Resizer" and "Project Builder" folders to sit
next to this folder. Apps started here stop when you close the Control Centre window.
Removed projects are moved to "Artwork Resizer/projects_removed", not deleted.

LICENSE MANAGER  (vendor tool – keep private)
===============
Issues the yearly licence codes for Artwork Resizer and Project Builder.

IMPORTANT
  * private_key.hex in this folder is the signing key. Anyone who has it can create
    licence codes. Never send this folder to customers. Keep a backup somewhere safe:
    if it is lost, new codes cannot be made for the apps already delivered.
  * data/issued_licences.csv is your register of every code issued.

Start
  Double-click "Start License Manager.command" (opens http://localhost:8770).
  First time: set a manager password (10+ characters).

Issue a code
  Enter who it is for, tick the apps, pick the start date (the end date is one year later)
  and click "Generate code". Copy the code, or "Copy email text" for a ready message.

Renew
  In "Issued licences" click Renew: the form is filled in to start the day after the
  current licence ends. Generate and send the new code before the old one runs out.
  The apps show a reminder 30 days before the end date.
