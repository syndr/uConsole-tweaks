VERSION ?= 0.2.2
DEB := uconsole-tweaks.deb

SOURCES := $(wildcard tweaks/*/*) make_uconsole-tweaks_package.sh

SERVICES := zmk-cursor-scroll

.PHONY: all build install uninstall reinstall clean status logs help

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

help:
	@echo "Targets:"
	@echo "  build       build $(DEB) (default)"
	@echo "  install     build + apt-install the package (auto-resolves deps)"
	@echo "  reinstall   clean + install"
	@echo "  uninstall   dpkg -r the package"
	@echo "  clean       remove build artifacts"
	@echo "  status      systemctl status for all shipped services"
	@echo "  logs        follow journalctl for all shipped services"
	@echo ""
	@echo "Override version: make VERSION=0.2.0 build"
