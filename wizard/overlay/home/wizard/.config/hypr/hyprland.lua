-- Wizard Desktop session. Hyprland is only the invisible compositor here:
-- one full-bleed window (the Wizard), no bars, no gaps, no Omarchy desktop.
-- Every optional block runs under pcall so one bad option can never stop the
-- Wizard window from launching.

local function try(label, fn)
  local ok, err = pcall(fn)
  if not ok then
    local f = io.open((os.getenv("HOME") or "/tmp") .. "/.local/state/wizard-hypr-errors.log", "a")
    if f then f:write(label .. ": " .. tostring(err) .. "\n"); f:close() end
  end
end

hl.on("hyprland.start", function()
  hl.exec_cmd("systemctl --user import-environment $(env | cut -d'=' -f 1)")
  hl.exec_cmd("dbus-update-activation-environment --systemd --all")
  hl.exec_cmd("/opt/wizard/bin/wizard-kiosk")
end)

try("env", function()
  hl.env("XCURSOR_SIZE", "24")
  hl.env("GDK_BACKEND", "wayland,x11,*")
  hl.env("QT_QPA_PLATFORM", "wayland;xcb")
  hl.env("ELECTRON_OZONE_PLATFORM_HINT", "wayland")
  hl.env("OZONE_PLATFORM", "wayland")
  hl.env("XDG_SESSION_TYPE", "wayland")
  hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
  hl.env("XDG_SESSION_DESKTOP", "Hyprland")
end)

try("monitor", function()
  hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
end)

try("look", function()
  hl.config({
    general = { gaps_in = 0, gaps_out = 0, border_size = 0, resize_on_border = false, layout = "dwindle" },
    decoration = { rounding = 0, shadow = { enabled = false }, blur = { enabled = false } },
    animations = { enabled = false },
    misc = { disable_hyprland_logo = true, disable_splash_rendering = true },
  })
end)

try("background", function()
  hl.config({ misc = { background_color = "rgb(0b0b12)" } })
end)

-- No Hyprland welcome / update / donation screens: this is the Wizard, not a desktop.
try("ecosystem", function()
  hl.config({ ecosystem = { no_update_news = true, no_donation_nag = true } })
end)

try("input", function()
  hl.config({
    input = {
      kb_layout = "us",
      follow_mouse = 1,
      repeat_rate = 40,
      repeat_delay = 250,
      touchpad = { natural_scroll = true, clickfinger_behavior = true, scroll_factor = 0.4 },
    },
  })
end)

-- Mac-native shortcuts: the Command key arrives as SUPER; translate the
-- everyday editing chords to the CTRL chords Chromium expects.
local function send_once(mods, key)
  return function()
    hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "down" }))
    hl.timer(function()
      hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "up" }))
    end, { timeout = 50, type = "oneshot" })
  end
end

for _, key in ipairs({ "C", "V", "X", "A", "Z", "F", "L", "R", "minus", "equal", "0" }) do
  try("bind " .. key, function()
    hl.bind("SUPER + " .. key, send_once("CTRL", key), { description = "Mac " .. key })
  end)
end
try("bind redo", function()
  hl.bind("SUPER + SHIFT + Z", send_once("CTRL SHIFT", "Z"), { description = "Mac redo" })
end)

-- Hidden escape hatch for the builders: a terminal. Never shown in the UI.
try("bind terminal", function()
  hl.bind("SUPER + CTRL + ALT + T", hl.dsp.exec_cmd("foot"), { description = "Wizard terminal" })
end)

-- QEMU Retina/fullscreen sizing: follow the live Mac window size.
try("display-sync", function()
  local file = io.open("/proc/cmdline", "r")
  local cmdline = file and file:read("*a") or ""
  if file then file:close() end
  if (" " .. cmdline .. " "):find(" omarchy.qemu_virgl=1 ", 1, true) then
    hl.config({ cursor = { invisible = true } })
    hl.on("hyprland.start", function()
      hl.exec_cmd("/usr/local/bin/omarchy-native-display-sync")
    end)
    hl.on("config.reloaded", function()
      hl.exec_cmd("/usr/local/bin/omarchy-native-display-sync --once")
    end)
  end
end)

try("apple-keyboard", function()
  dofile("/usr/share/try-omarchy/apple-keyboard-input.lua")
end)
