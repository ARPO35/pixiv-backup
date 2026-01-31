include $(TOPDIR)/rules.mk

PKG_NAME:=pixiv-backup
PKG_VERSION:=1.0.0
PKG_RELEASE:=1

PKG_MAINTAINER:=OpenWrt User <user@example.com>
PKG_LICENSE:=GPL-3.0
PKG_LICENSE_FILES:=LICENSE

include $(INCLUDE_DIR)/package.mk

define Package/pixiv-backup
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=Pixiv Backup Service for OpenWrt
  DEPENDS:=+python3 +python3-pip +python3-aiohttp +python3-sqlite3 +python3-pillow +python3-requests
  PKGARCH:=all
endef

define Package/pixiv-backup/description
  A service to backup pixiv user bookmarks and following lists with LuCI interface.
  Automatically downloads images and metadata to configured output directory.
endef

define Package/luci-app-pixiv-backup
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=LuCI界面 for Pixiv Backup
  DEPENDS:=+pixiv-backup +luci +luci-compat +luci-lib-json
  PKGARCH:=all
endef

define Package/luci-app-pixiv-backup/description
  LuCI Configuration Interface for Pixiv Backup Service.
endef

define Build/Configure
  true
endef

define Build/Compile
  true
endef

# 主程序安装
define Package/pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) ./src/pixiv-backup/main.py $(1)/usr/bin/pixiv-backup
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup
	$(CP) ./src/pixiv-backup/*.py $(1)/usr/share/pixiv-backup/
	$(CP) ./src/pixiv-backup/modules $(1)/usr/share/pixiv-backup/
	$(CP) ./src/pixiv-backup/tools $(1)/usr/share/pixiv-backup/
	
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./src/init.d/pixiv-backup $(1)/etc/init.d/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_DATA) ./src/config/pixiv-backup $(1)/etc/config/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/hotplug.d/iface
	$(INSTALL_DATA) ./src/hotplug/99-pixiv-backup $(1)/etc/hotplug.d/iface/99-pixiv-backup
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/templates
	$(INSTALL_DATA) ./src/pixiv-backup/templates/* $(1)/usr/share/pixiv-backup/templates/
endef

# LuCI界面安装
define Package/luci-app-pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua $(1)/usr/lib/lua/luci/controller/
	
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./src/luci-app-pixiv-backup/luasrc/model/cbi/pixiv-backup.lua $(1)/usr/lib/lua/luci/model/cbi/
	
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view
	$(INSTALL_DATA) ./src/luci-app-pixiv-backup/luasrc/view/pixiv-backup.htm $(1)/usr/lib/lua/luci/view/
	
	$(INSTALL_DIR) $(1)/www/luci-static/resources/pixiv-backup
	$(INSTALL_DATA) ./src/luci-app-pixiv-backup/htdocs/* $(1)/www/luci-static/resources/pixiv-backup/
endef

$(eval $(call BuildPackage,pixiv-backup))
$(eval $(call BuildPackage,luci-app-pixiv-backup))