module("luci.controller.pixiv-backup", package.seeall)

local fs = require("nixio.fs")

function index()
    entry({"admin", "services", "pixiv-backup"}, cbi("pixiv-backup"), _("Pixiv备份"), 60).dependent = false
    entry({"admin", "services", "pixiv-backup", "status"}, call("action_status")).leaf = true
    entry({"admin", "services", "pixiv-backup", "logs"}, call("action_logs")).leaf = true
    entry({"admin", "services", "pixiv-backup", "start"}, call("action_start")).leaf = true
    entry({"admin", "services", "pixiv-backup", "stop"}, call("action_stop")).leaf = true
end

function action_status()
    local uci = require("luci.model.uci").cursor()
    local sys = require("luci.sys")
    local http = require("luci.http")
    
    local result = {
        service_status = "stopped",
        config_status = "unconfigured",
        last_run = nil,
        stats = {
            total_downloaded = 0,
            last_24h = 0,
            storage_used = "0MB"
        }
    }
    
    -- 检查服务状态
    local service_pid = sys.exec("pgrep -f 'pixiv-backup' 2>/dev/null")
    if service_pid and service_pid ~= "" then
        result.service_status = "running"
    end
    
    -- 检查配置
    local main = uci:get_all("pixiv-backup", "settings")
    if main and main.enabled == "1" and main.user_id and main.user_id ~= "" and main.refresh_token and main.refresh_token ~= "" then
        result.config_status = "configured"
    end
    
    -- 获取输出目录
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    
    -- 获取统计数据
    local db_path = output_dir .. "/data/pixiv.db"
    if fs.access(db_path) then
        local count = sys.exec("sqlite3 '" .. db_path .. "' 'SELECT COUNT(*) FROM illusts;' 2>/dev/null")
        if count and count ~= "" then
            result.stats.total_downloaded = tonumber(count:gsub("%s+", "")) or 0
        end
        
        -- 计算存储使用量
        local du = sys.exec("du -sh '" .. output_dir .. "/img/' 2>/dev/null | cut -f1")
        if du and du ~= "" then
            result.stats.storage_used = du:gsub("%s+", "")
        end
    end
    
    -- 获取最后运行时间
    local last_run_file = output_dir .. "/data/last_run.txt"
    if fs.access(last_run_file) then
        local content = fs.readfile(last_run_file)
        if content then
            result.last_run = content:gsub("%s+$", "")
        end
    end
    
    http.prepare_content("application/json")
    http.write_json(result)
end

function action_logs()
    local sys = require("luci.sys")
    local http = require("luci.http")
    
    -- 尝试多个日志位置
    local log_files = {
        "/var/log/pixiv-backup.log",
        "/mnt/sda1/pixiv-backup/data/logs/pixiv-backup.log"
    }
    
    local logs = nil
    for _, log_file in ipairs(log_files) do
        if fs.access(log_file) then
            logs = sys.exec("tail -100 '" .. log_file .. "' 2>/dev/null")
            break
        end
    end
    
    http.prepare_content("text/plain; charset=utf-8")
    http.write(logs or "暂无日志")
end

function action_start()
    local sys = require("luci.sys")
    local http = require("luci.http")
    
    local result = sys.exec("/etc/init.d/pixiv-backup start 2>&1")
    http.prepare_content("text/plain; charset=utf-8")
    http.write(result or "服务启动命令已执行")
end

function action_stop()
    local sys = require("luci.sys")
    local http = require("luci.http")
    
    local result = sys.exec("/etc/init.d/pixiv-backup stop 2>&1")
    http.prepare_content("text/plain; charset=utf-8")
    http.write(result or "服务停止命令已执行")
end