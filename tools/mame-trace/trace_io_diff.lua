-- trace_io_diff.lua — frame-resolved I/O-read differential capture for Superman.
--
-- Installs read taps over EVERY non-ROM device region the 68K can touch and
-- records, per (PC, addr), the distinct values seen and the frames where the
-- value CHANGED. The point: find reads whose value VARIES across frames (real
-- hardware state the boot polls) where the interpreter returns a constant.
-- Also taps writes (esp. the C-Chip command port $900C01 and the video regs)
-- so the comparator can reconstruct command state and write-then-poll gates.
--
-- Run headless (model on run_trace.sh):
--   mame superman -rompath ./roms -video none -sound none -nothrottle \
--     -skip_gameinfo -seconds_to_run 15 -autoboot_script trace_io_diff.lua \
--     -autoboot_delay 0 -nvram_directory ./nvram -cfg_directory ./cfg
-- Env: IODIFF_FRAMES (default 600), IODIFF_LOG (default io_diff.log).

local FRAMES_TO_RUN = tonumber(os.getenv("IODIFF_FRAMES") or "600")
local LOGFILE       = os.getenv("IODIFF_LOG") or "io_diff.log"

local log = io.open(LOGFILE, "w")
local function w(s) log:write(s .. "\n") end

local rhist, rorder = {}, {}   -- read  history: key "PC:ADDR" -> entry
local whist, worder = {}, {}   -- write history
local frame = 0
local cpu, prog

-- MUST keep tap handles GLOBAL (a local gets GC'd, removing the tap -> crash).
IODIFF_TAPS = {}

local function pc()
  local ok, v = pcall(function() return cpu.state["PC"].value end)
  return ok and v or 0
end

local function rec(tbl, order, addr, data)
  local p = pc()
  local key = string.format("%06X:%06X", p, addr)
  local e = tbl[key]
  if not e then
    e = { pc = p, addr = addr, count = 0, distinct = {}, nvals = 0, last = -1, changes = {} }
    tbl[key] = e; order[#order+1] = key
  end
  e.count = e.count + 1
  if e.distinct[data] == nil then e.distinct[data] = true; e.nvals = e.nvals + 1 end
  if data ~= e.last then
    if #e.changes < 24 then e.changes[#e.changes+1] = string.format("f%d=$%02X", frame, data) end
    e.last = data
  end
end

-- one read+write tap per region; pcall so unmapped regions don't abort the run
local REGIONS = {
  {0x300000, 0x3FFFFF, "vid300"},
  {0x400000, 0x4FFFFF, "vid400"},
  {0x500000, 0x5FFFFF, "dip500"},
  {0x600000, 0x6FFFFF, "vid600"},
  {0x700000, 0x7FFFFF, "io700"},
  {0x800000, 0x8FFFFF, "snd800"},
  {0x900000, 0x900FFF, "cchip"},
}

local function install()
  cpu  = manager.machine.devices[":maincpu"]
  prog = cpu.spaces["program"]
  for _, r in ipairs(REGIONS) do
    local lo, hi, nm = r[1], r[2], r[3]
    local ok1 = pcall(function()
      IODIFF_TAPS[#IODIFF_TAPS+1] = prog:install_read_tap(lo, hi, nm.."_r",
        function(off, data, mask) rec(rhist, rorder, off, data & 0xff); return data end)
    end)
    local ok2 = pcall(function()
      IODIFF_TAPS[#IODIFF_TAPS+1] = prog:install_write_tap(lo, hi, nm.."_w",
        function(off, data, mask) rec(whist, worder, off, data & 0xff); return data end)
    end)
    w(string.format("# tap %-8s $%06X-$%06X  read=%s write=%s", nm, lo, hi, tostring(ok1), tostring(ok2)))
  end
  w("# I/O-read differential — Superman (MAME)")
  w(string.format("# frames=%d", FRAMES_TO_RUN))
end

local function dump(title, tbl, order)
  -- sort: varying (nvals desc) first, then by count desc
  local keys = {}
  for _, k in ipairs(order) do keys[#keys+1] = k end
  table.sort(keys, function(a, b)
    local ea, eb = tbl[a], tbl[b]
    if ea.nvals ~= eb.nvals then return ea.nvals > eb.nvals end
    return ea.count > eb.count
  end)
  w(""); w("# === " .. title .. " (PC ADDR count nvals changes) — varying first ===")
  for _, k in ipairs(keys) do
    local e = tbl[k]
    w(string.format("%s  PC=%06X ADDR=%06X count=%d nvals=%d  [%s]",
      (e.nvals > 1 and "VARY" or "const"), e.pc, e.addr, e.count, e.nvals,
      table.concat(e.changes, " ")))
  end
end

local function on_frame()
  frame = frame + 1
  if frame >= FRAMES_TO_RUN then
    dump("READS", rhist, rorder)
    dump("WRITES", whist, worder)
    log:close()
    manager.machine:exit()
  end
end

install()
if emu.register_frame_done then emu.register_frame_done(on_frame)
elseif emu.register_frame then emu.register_frame(on_frame) end
