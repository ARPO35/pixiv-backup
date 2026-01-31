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
  DEPENDS:=+python3 +python3-requests
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
  TITLE:=LuCI Interface for Pixiv Backup
  DEPENDS:=+pixiv-backup
  PKGARCH:=all
endef

define Package/luci-app-pixiv-backup/description
  LuCI Configuration Interface for Pixiv Backup Service.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Configure
endef

define Build/Compile
endef

# 主程序安装
define Package/pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/pixiv-backup/main.py $(1)/usr/bin/pixiv-backup
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/*.py $(1)/usr/share/pixiv-backup/
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/modules
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/modules/*.py $(1)/usr/share/pixiv-backup/modules/
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/tools
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/tools/*.py $(1)/usr/share/pixiv-backup/tools/
	
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/init.d/pixiv-backup $(1)/etc/init.d/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) $(PKG_BUILD_DIR)/config/pixiv-backup $(1)/etc/config/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/hotplug.d/iface
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/hotplug/99-pixiv-backup $(1)/etc/hotplug.d/iface/99-pixiv-backup
endef

# LuCI界面安装
define Package/luci-app-pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua $(1)/usr/lib/lua/luci/controller/
	
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/luci-app-pixiv-backup/luasrc/model/cbi/pixiv-backup.lua $(1)/usr/lib/lua/luci/model/cbi/
	
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view/pixiv-backup
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/luci-app-pixiv-backup/luasrc/view/pixiv-backup.htm $(1)/usr/lib/lua/luci/view/pixiv-backup/
endef

define Package/pixiv-backup/conffiles
/etc/config/pixiv-backup
endef

$(eval $(call BuildPackage,pixiv-backup))
$(eval $(call BuildPackage,luci-app-pixiv-backup))