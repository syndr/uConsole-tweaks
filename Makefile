VERSION ?= 0.2.3
DEB := uconsole-tweaks.deb

SOURCES := $(wildcard tweaks/*/*) make_uconsole-tweaks_package.sh

SERVICES := zmk-cursor-scroll

.PHONY: all build install uninstall reinstall clean status logs help \
	zmk-uc9900 zmk-uc9900-stock zmk-uc9900-backup zmk-uc9900-flash

all: $(DEB)

build: $(DEB)

$(DEB): $(SOURCES)
	ENV_VERSION=$(VERSION) bash ./make_uconsole-tweaks_package.sh

install: $(DEB)
	sudo apt install -y ./$(DEB)

reinstall: clean install

uninstall:
	sudo dpkg -r uconsole-tweaks

clean:
	rm -f $(DEB)
	rm -rf uconsole-tweaks

status:
	systemctl status --no-pager $(addsuffix .service,$(SERVICES))

logs:
	sudo journalctl -f $(addprefix -u ,$(SERVICES))

# Keyboard firmware (see zmk-uc9900/README.md). Not part of the .deb.
zmk-uc9900:
	./zmk-uc9900/build.sh custom

zmk-uc9900-stock:
	./zmk-uc9900/build.sh stock

zmk-uc9900-backup:
	./zmk-uc9900/flash.sh backup $(if $(RESTORE),--restore)

zmk-uc9900-flash:
	@test -n "$(UF2)" || { echo "usage: make zmk-uc9900-flash UF2=zmk-uc9900/out/<image>.uf2"; exit 2; }
	./zmk-uc9900/flash.sh flash $(UF2)

help:
	@echo "Targets:"
	@echo "  build       build $(DEB) (default)"
	@echo "  install     build + apt-install the package (auto-resolves deps)"
	@echo "  reinstall   clean + install"
	@echo "  uninstall   dpkg -r the package"
	@echo "  clean       remove build artifacts"
	@echo "  status      systemctl status for all shipped services"
	@echo "  logs        follow journalctl for all shipped services"
	@echo "  zmk-uc9900         build our keyboard firmware"
	@echo "  zmk-uc9900-stock   build the stock keyboard firmware (recovery image)"
	@echo "  zmk-uc9900-backup  save the firmware currently on the keyboard (RESTORE=1 writes it back)"
	@echo "  zmk-uc9900-flash   flash a keyboard firmware image: UF2=<file>"
	@echo ""
	@echo "Override version: make VERSION=0.2.0 build"
