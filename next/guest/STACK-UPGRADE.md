# Mac MVP runtime patch — integration and existing-disk recipe

This is a one-time internal candidate, not an updater. Parent owns assembly/release. Do **not** run `wizard-apps factory` against a user's disk: that command removes optional apps/data by design.

## Components / payload

Build the Service image from this slice's Service + UX model adapter, **plus the separate UX worker's commits**. Preserve the shipped local tag `wizard-shell:mac-mvp-20261013` until the controller chooses a version and updates WAM's pin together. Save that exact image to `wizard-shell.tar` on Thales. Payload directory:

```
wam/wam/                    # exact slice WAM package
source/next/guest/upgrade-mvp-stack.py
overlay/opt/wizard/local-proxy.conf
overlay/opt/wizard/product-plugin/{__init__.py,plugin.yaml}
overlay/opt/wizard/bin/wizard-product-configure
overlay/opt/wizard/setup/hermes_brain.py
wizard-shell.tar
```

SHA256 the payload and image on Thales for the private delivery receipt. No accounts/credentials from a QA disk belong in it. The new factory must run `wizard-product-configure` and `wam fresh-agent connect` once **after** the updated WAM, guest overlay and image are installed. The modified factory command does this. A remaster should invoke these directly rather than trim an existing disk.

## Existing MVP disk — state preserving

1. Quit Wizard MVP and let its owned guest stop cleanly. Resolve the owner's actual `DataHome` from **that app's** settings; never assume the default and never change other VM preferences. Retain the existing `os/disk.img`, files-folder selection and shared Mac folder. Make an APFS clone/backup of the stopped disk on Thales/external storage (or encrypted R2 for retention), not on the VPS. Do not download/replace the disk with a factory image.
2. Enable the existing opt-in dev shell only for this maintenance launch (`<DataHome>/dev-shell`). Start the **same** native installed app and disk. This is the established local vsock9200 maintenance route, not a published remote admin port. Alternative: run the script through the owner's existing terminal/root administrative path in the guest. Do not bake a secret, add an SSH key or reset onboarding.
3. Make the **verified payload** available read-only to the guest (a temporary virtio-fs maintenance share in the isolated build/QA harness, or copy the small script/package and image through the chosen shared folder; remove it afterward). Run in the guest:
   ```
   python3 <payload>/source/next/guest/upgrade-mvp-stack.py <payload>
   python3 <payload>/source/next/guest/upgrade-mvp-stack.py <payload> --apply
   ```
   Pause chat work while applying. Preflight refuses an unknown/non-MVP layout. The apply path backs up only changed metadata into private `/var/lib/wizard/patches/mac-stack-v1`, installs the named WAM package/plugin/guest files, loads the exact new local Service image, regenerates supported Runtipi user-config through `wam fresh-agent connect`, refreshes the registry, and restarts only the affected WAM user units, local ingress and this guest's Hermes engine. It does not call bootstrap, uninstall, factory trim, auth login, free-tier minting, home reset or disk creation.
4. Verify actual runtime, not just script return: Files opens and lists/round-trips a file in the **same chosen Mac folder**; AI Accounts Get/Open loads styled controls and Test reports the real disconnected/connected state; model list contains only configured routes; fresh chat answers as the owner's named Wizard on WizardOS; explicitly asking provenance still yields Hermes Agent / Nous Research. Check previous chats/messages/files/apps and account hashes/counts remain; read `/var/lib/wizard/patches/mac-stack-v1/applied.json` and the new Service image ID. Remove maintenance payload/share and the temporary `dev-shell` marker, then quit/reopen and recheck persistence.
5. Rollback if needed: with the app/guest stopped, restore the **same user's stopped-disk backup**, not a factory disk. It already includes pre-patch chat/account/app data; leave the external shared folder in place. Keep logs free of credentials. The metadata backup is diagnosis/targeted rollback material, not a complete substitute for the stopped-disk backup.

## Routing/security seam

The Mac native bridge remains127.0.0.1:48023 → guestvsock8923. Guest nginx dispatches main `Host:127.0.0.1` to Service8796 and installed-app `Host:localhost` to the app-only listener8798. Browser origins differ; localhost serves `/apps/` only and returns404 for all control endpoints. WAM opts into this only with `app-manager.json.mac_apps_origin="http://localhost:48023"`; ordinary non-Mac fresh-agent boxes are unchanged. Do not weaken main-origin authorization or put app scripts in Wizard's control origin.

The Service contains narrowly audited base-path adapters for the pinned Files `def6a08...` and AI Accounts `ddc9dc5...` recipes, not a global HTML rewrite. WAM reads the installed compose's main internal port (Files8080, not its published8794). No source/recipe/data file inside Runtipi is hand-edited. AI Accounts' source was isolated/read at the public pinned commit; its original sources do not need a rebuild or publication.

## Truth boundaries

A configured provider is not a proof of credit or physical human OAuth completion. The model picker uses the running engine's authenticated provider state, not installed-app presence. Wizard product guidance is an additive supported prompt-section plugin; existing SOUL/custom names and engine/model/provider provenance are retained. Stock Hermes core stays byte-unchanged.
