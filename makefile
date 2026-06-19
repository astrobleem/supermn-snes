# Superman Arcade → SNES Port
# Build system

builddir := build
sourcedir := src
distdir := distribution

romext := sfc
romfile := build/superman.$(romext)

# Poppy assembler
DOTNET_ROOT := /home/chad/.dotnet10
POPPY := DOTNET_ROOT=$(DOTNET_ROOT) PATH="$(DOTNET_ROOT):$$PATH" dotnet /home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll

.PHONY: all clean rom spritetest

all: rom

# Assemble with Poppy, then build ROM with header
rom: $(romfile)

$(romfile): src/main.pasm
	$(POPPY) src/main.pasm
	python3 build_rom.py

# Sprite test ROM
spritetest: build/sprite_test.sfc

build/sprite_test.sfc: src/sprite_test.pasm
	$(POPPY) src/sprite_test.pasm
	python3 build_sprite_test_rom.py

clean:
	rm -rf $(builddir) $(distdir) src/main.bin src/main.pansy src/sprite_test.bin src/sprite_test.pansy
	@echo "Build artifacts cleaned"
