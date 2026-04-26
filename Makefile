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
  DEPENDS:=+python3 +python3-requests +python3-pyparsing +ca-bundle
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

define Download/pixivpy3
  URL:=https://files.pythonhosted.org/packages/09/f0/8f40168c6e4aa824543d67d17b3104f00c6e9bda53709693c1a0e30e0b72
  FILE:=pixivpy3-3.7.5-py3-none-any.whl
  HASH:=3f9c3c9236d9924de9f80390cc3d1cc78bc494175a94cc9903f7b60308efca72
endef

define Download/cloudscraper
  URL:=https://files.pythonhosted.org/packages/81/97/fc88803a451029688dffd7eb446dc1b529657577aec13aceff1cc9628c5d
  FILE:=cloudscraper-1.2.71-py2.py3-none-any.whl
  HASH:=76f50ca529ed2279e220837befdec892626f9511708e200d48d5bb76ded679b0
endef

define Download/requests-toolbelt
  URL:=https://files.pythonhosted.org/packages/3f/51/d4db610ef29373b879047326cbf6fa98b6c1969d6f6dc423279de2b1be2c
  FILE:=requests_toolbelt-1.0.0-py2.py3-none-any.whl
  HASH:=cccfdd665f0a24fcf4726e690f65639d272bb0637b9b92dfd91a5568ccf6bd06
endef

define Download/typing-extensions
  URL:=https://files.pythonhosted.org/packages/26/9f/ad63fc0248c5379346306f8668cda6e2e2e9c95e01216d2b8ffd9ff037d0
  FILE:=typing_extensions-4.12.2-py3-none-any.whl
  HASH:=04e5ca0351e0f3f85c6853954072df659d0d13fac324d0072316b67d7794700d
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
	$(INSTALL_DIR) $(PKG_BUILD_DIR)/docs
	$(CP) ./docs/*.md $(PKG_BUILD_DIR)/docs/
	$(INSTALL_DIR) $(PKG_BUILD_DIR)/vendor
	unzip -q -o $(DL_DIR)/pixivpy3-3.7.5-py3-none-any.whl -d $(PKG_BUILD_DIR)/vendor
	unzip -q -o $(DL_DIR)/cloudscraper-1.2.71-py2.py3-none-any.whl -d $(PKG_BUILD_DIR)/vendor
	unzip -q -o $(DL_DIR)/requests_toolbelt-1.0.0-py2.py3-none-any.whl -d $(PKG_BUILD_DIR)/vendor
	unzip -q -o $(DL_DIR)/typing_extensions-4.12.2-py3-none-any.whl -d $(PKG_BUILD_DIR)/vendor
endef

define Build/Configure
endef

define Build/Compile
endef

# 主程序安装
define Package/pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/*.py $(1)/usr/share/pixiv-backup/
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/modules
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/modules/*.py $(1)/usr/share/pixiv-backup/modules/
	
	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/tools
	$(CP) $(PKG_BUILD_DIR)/pixiv-backup/tools/*.py $(1)/usr/share/pixiv-backup/tools/

	$(INSTALL_DIR) $(1)/usr/share/pixiv-backup/vendor
	$(CP) $(PKG_BUILD_DIR)/vendor/* $(1)/usr/share/pixiv-backup/vendor/
	
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/pixiv-backup/main.py $(1)/usr/bin/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/init.d/pixiv-backup $(1)/etc/init.d/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) $(PKG_BUILD_DIR)/config/pixiv-backup $(1)/etc/config/pixiv-backup
	
	$(INSTALL_DIR) $(1)/etc/hotplug.d/iface
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/hotplug/99-pixiv-backup $(1)/etc/hotplug.d/iface/99-pixiv-backup

	$(INSTALL_DIR) $(1)/usr/share/doc/pixiv-backup
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/docs/refresh-token.md $(1)/usr/share/doc/pixiv-backup/refresh-token.md
endef

# LuCI界面安装
define Package/luci-app-pixiv-backup/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua $(1)/usr/lib/lua/luci/controller/
	
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/luci-app-pixiv-backup/luasrc/model/cbi/pixiv-backup.lua $(1)/usr/lib/lua/luci/model/cbi/
endef

define Package/pixiv-backup/conffiles
/etc/config/pixiv-backup
endef

$(eval $(call Download,pixivpy3))
$(eval $(call Download,cloudscraper))
$(eval $(call Download,requests-toolbelt))
$(eval $(call Download,typing-extensions))

$(eval $(call BuildPackage,pixiv-backup))
$(eval $(call BuildPackage,luci-app-pixiv-backup))
