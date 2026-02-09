module("luci.controller.pixiv-backup", package.seeall)

local fs = require("nixio.fs")
local sys = require("luci.sys")
local util = require("luci.util")
local http = require("luci.http")
local jsonc = require("luci.jsonc")

local function _norm(v)
    local s = tostring(v or "-")
    s = s:gsub("[\r\n]", " ")
    s = s:gsub("%s+", " ")
    if s == "" then
        s = "-"
    end
    return s
end

local function write_luci_audit(output_dir, source, action, status, detail)
    local log_dir = (output_dir or "/mnt/sda1/pixiv-backup") .. "/data/logs"
    local log_file = log_dir .. "/pixiv-backup-" .. os.date("%Y%m%d") .. ".log"
    local ip = _norm(http.getenv("REMOTE_ADDR"))
    local ua = _norm(http.getenv("HTTP_USER_AGENT"))
    local line = string.format(
        "%s - pixiv-backup.audit - INFO - event=luci_action source=%s action=%s status=%s ip=%s ua=%s detail=%s\n",
        os.date("%Y-%m-%d %H:%M:%S"),
        _norm(source),
        _norm(action),
        _norm(status),
        ip,
        ua,
        _norm(detail)
    )

    fs.mkdirr(log_dir)
    local f = io.open(log_file, "a")
    if f then
        f:write(line)
        f:close()
    end

    local syslog_msg = string.format(
        "event=luci_action source=%s action=%s status=%s ip=%s detail=%s",
        _norm(source), _norm(action), _norm(status), ip, _norm(detail)
    )
    sys.call("logger -t pixiv-backup-audit " .. util.shellquote(syslog_msg))
end

local function normalize_recent_error_item(item, fallback_time)
    if type(item) ~= "table" then
        return nil
    end
    local detail = tostring(item.detail or "")
    detail = detail:gsub("\\r\\n", "\n"):gsub("\\n", "\n")
    local pid = tostring(item.pid or "-")
    local action = tostring(item.action or "-")
    local url = tostring(item.url or "")
    local err = tostring(item.error or "")
    local t = tostring(item.time or fallback_time or "-")

    url = url:gsub("\\r\\n", "\n"):gsub("\\n", "\n"):gsub("\r\n", "\n"):gsub("\r", "\n")
    url = url:match("([^\n]+)") or url
    url = url:gsub("^%s*[Uu][Rr][Ll]%s*[:=]%s*", "")
    err = err:gsub("\\r\\n", "\n"):gsub("\\n", "\n"):gsub("\r\n", "\n"):gsub("\r", "\n")
    err = err:gsub("^%s*错误%s*[:=]%s*", "")
    err = err:gsub("^%s*[Ee][Rr][Rr][Oo][Rr]%s*[:=]%s*", "")

    if (pid == "-" or pid == "") and detail ~= "" then
        local m = detail:match("pid%s*=%s*(%d+)")
        if m then
            pid = m
        end
    end
    if (url == "") and detail ~= "" then
        local m = detail:match("url%s*=%s*(%S+)")
        if m then
            url = m
        else
            local m2 = detail:match("[Uu][Rr][Ll]%s*[:=]%s*([^\n]+)")
            if m2 then
                url = m2
            end
        end
    end
    if (err == "") and detail ~= "" then
        local m = detail:match("error%s*=%s*(.+)$")
        if m then
            err = m
        else
            local m2 = detail:match("\n%s*错误%s*[:=]%s*(.+)$")
            if not m2 then
                m2 = detail:match("\r%s*错误%s*[:=]%s*(.+)$")
            end
            if m2 then
                err = m2
            else
                err = detail
            end
        end
    end
    if url == "" and pid:match("^%d+$") then
        url = "https://www.pixiv.net/artworks/" .. pid
    end
    if err == "" then
        err = detail ~= "" and detail or "-"
    end
    if detail == "" then
        detail = err
    end
    return {
        time = t,
        pid = pid ~= "" and pid or "-",
        action = action ~= "" and action or "-",
        url = url,
        error = err,
        detail = detail,
    }
end

local function is_pid_downloaded(db_path, pid)
    if not db_path or db_path == "" then
        return false
    end
    local p = tostring(pid or "")
    if not p:match("^%d+$") then
        return false
    end
    if sys.call("command -v sqlite3 >/dev/null 2>&1") ~= 0 then
        return false
    end
    local sql = "SELECT downloaded FROM illusts WHERE illust_id=" .. p .. " LIMIT 1;"
    local cmd = "sqlite3 " .. util.shellquote(db_path) .. " " .. util.shellquote(sql) .. " 2>/dev/null"
    local out = (sys.exec(cmd) or ""):gsub("%s+", "")
    return out == "1"
end

function index()
    entry({"admin", "services", "pixiv-backup"}, cbi("pixiv-backup"), _("Pixiv备份"), 60).dependent = false
    entry({"admin", "services", "pixiv-backup", "status"}, call("action_status")).leaf = true
    entry({"admin", "services", "pixiv-backup", "logs"}, call("action_logs")).leaf = true
    entry({"admin", "services", "pixiv-backup", "start"}, call("action_start")).leaf = true
    entry({"admin", "services", "pixiv-backup", "stop"}, call("action_stop")).leaf = true
end

function action_status()
    local uci = require("luci.model.uci").cursor()
    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    local db_path = output_dir .. "/data/pixiv.db"
    local result = {
        service_status = "stopped",
        config_status = "unconfigured",
        last_run = nil,
        runtime = {},
        recent_errors = {},
        stats = {
            total_downloaded = 0,
            total_processed_all = 0,
            last_24h = 0,
            storage_used = "0MB"
        },
        queue_summary = {
            total = 0,
            pending = 0,
            running = 0,
            failed = 0,
            permanent_failed = 0,
            done = 0,
            next_retry_at = nil
        },
    }
    
    -- 检查服务状态
    if sys.call("/etc/init.d/pixiv-backup running >/dev/null 2>&1") == 0 then
        result.service_status = "running"
    end
    
    -- 检查配置
    if main and main.enabled == "1" and main.user_id and main.user_id ~= "" and main.refresh_token and main.refresh_token ~= "" then
        result.config_status = "configured"
    end
    
    -- 统计存储使用量
    local du = sys.exec("du -sh '" .. output_dir .. "/img/' 2>/dev/null | cut -f1")
    if du and du ~= "" then
        result.stats.storage_used = du:gsub("%s+", "")
    end
    
    -- 获取最后运行时间
    local last_run_file = output_dir .. "/data/last_run.txt"
    if fs.access(last_run_file) then
        local content = fs.readfile(last_run_file)
        if content then
            result.last_run = content:gsub("%s+$", "")
        end
    end

    -- 读取运行时状态
    local status_file = output_dir .. "/data/status.json"
    if fs.access(status_file) then
        local content = fs.readfile(status_file)
        if content and content ~= "" then
            local parsed = jsonc.parse(content)
            if parsed then
                result.runtime = parsed
                result.stats.total_processed_all = tonumber(parsed.total_processed_all or 0) or 0
                if type(parsed.recent_errors) == "table" then
                    for _, item in ipairs(parsed.recent_errors) do
                        local normalized = normalize_recent_error_item(item, parsed.updated_at or "-")
                        if normalized then
                            if not is_pid_downloaded(db_path, normalized.pid) then
                                table.insert(result.recent_errors, normalized)
                            end
                        end
                        if #result.recent_errors >= 10 then
                            break
                        end
                    end
                end
            end
        end
    end

    -- 服务未运行时，避免展示陈旧的 syncing/cooldown 状态
    if result.service_status ~= "running" then
        result.runtime.state = "stopped"
        result.runtime.phase = "stopped"
        result.runtime.message = "服务已停止"
        result.runtime.cooldown_reason = nil
        result.runtime.next_run_at = nil
        result.runtime.cooldown_seconds = 0
    end

    -- 最近错误兼容回退（旧字段仅有 last_error）
    if #result.recent_errors == 0 and result.runtime and result.runtime.last_error and result.runtime.last_error ~= "" then
        local fallback = normalize_recent_error_item({
            time = tostring(result.runtime.updated_at or "-"),
            pid = "-",
            action = tostring(result.runtime.phase or "-"),
            detail = tostring(result.runtime.last_error or "-")
        }, result.runtime.updated_at or "-")
        if fallback then
            table.insert(result.recent_errors, fallback)
        end
    end

    -- 队列信息（优先使用 runtime 中的汇总，缺失时读取 task_queue.json）
    local rp = tonumber(result.runtime.queue_pending or 0) or 0
    local rr = tonumber(result.runtime.queue_running or 0) or 0
    local rf = tonumber(result.runtime.queue_failed or 0) or 0
    local rpf = tonumber(result.runtime.queue_permanent_failed or 0) or 0
    local rd = tonumber(result.runtime.queue_done or 0) or 0
    local runtime_total = rp + rr + rf + rpf + rd
    if runtime_total > 0 then
        result.queue_summary.pending = rp
        result.queue_summary.running = rr
        result.queue_summary.failed = rf
        result.queue_summary.permanent_failed = rpf
        result.queue_summary.done = rd
        result.queue_summary.total = runtime_total
    else
        local queue_file = output_dir .. "/data/task_queue.json"
        if fs.access(queue_file) then
            local content = fs.readfile(queue_file)
            if content and content ~= "" then
                local parsed = jsonc.parse(content)
                local items = parsed and parsed.items or {}
                local next_retry = nil
                if type(items) == "table" then
                    for _, item in ipairs(items) do
                        local status = item.status or ""
                        result.queue_summary.total = result.queue_summary.total + 1
                        if status == "pending" then
                            result.queue_summary.pending = result.queue_summary.pending + 1
                        elseif status == "running" then
                            result.queue_summary.running = result.queue_summary.running + 1
                        elseif status == "failed" then
                            result.queue_summary.failed = result.queue_summary.failed + 1
                            local nra = item.next_retry_at
                            if nra and nra ~= "" and (not next_retry or nra < next_retry) then
                                next_retry = nra
                            end
                        elseif status == "permanent_failed" then
                            result.queue_summary.permanent_failed = result.queue_summary.permanent_failed + 1
                        elseif status == "done" then
                            result.queue_summary.done = result.queue_summary.done + 1
                        end
                    end
                end
                result.queue_summary.next_retry_at = next_retry
            end
        end
    end
    
    http.prepare_content("application/json")
    http.write_json(result)
end

function action_logs()
    local uci = require("luci.model.uci").cursor()
    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    local latest_log = sys.exec("ls -t '" .. output_dir .. "/data/logs/'pixiv-backup-*.log 2>/dev/null | head -n 1")
    latest_log = latest_log and latest_log:gsub("%s+$", "")

    local logs = nil
    if latest_log and latest_log ~= "" and fs.access(latest_log) then
        logs = sys.exec("tail -200 '" .. latest_log .. "' 2>/dev/null")
    end
    
    http.prepare_content("text/plain; charset=utf-8")
    http.write(logs or "暂无日志")
end

function action_start()
    local uci = require("luci.model.uci").cursor()

    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    local trigger_bin = fs.access("/usr/bin/pixiv-backup") and "/usr/bin/pixiv-backup" or "pixiv-backup"
    local rc = sys.call(trigger_bin .. " trigger >/tmp/pixiv-backup-start.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-start.log") or ""
    write_luci_audit(output_dir, "controller", "trigger", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
    http.prepare_content("text/plain; charset=utf-8")
    if result ~= "" then
        http.write(result)
    elseif rc == 0 then
        http.write("已请求立即扫描")
    else
        http.write("立即扫描触发失败：未返回详细输出")
    end
end

function action_stop()
    local rc = sys.call("pixiv-backup stop >/tmp/pixiv-backup-stop.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-stop.log") or ""
    local uci = require("luci.model.uci").cursor()
    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    write_luci_audit(output_dir, "controller", "stop", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
    http.prepare_content("text/plain; charset=utf-8")
    http.write(result ~= "" and result or "服务停止命令已执行")
end
