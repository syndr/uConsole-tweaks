# Out-of-tree build of the ocp8178 backlight module, for local testing.
# The package installs the same sources through DKMS (see dkms.conf).
obj-m += ocp8178_bl.o

KDIR ?= /lib/modules/$(shell uname -r)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
