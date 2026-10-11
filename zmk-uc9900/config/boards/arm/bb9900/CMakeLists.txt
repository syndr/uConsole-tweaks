# Board-specific code: the trackpad sensor driver and the trackpad light.
# Zephyr picks this file up from the board directory.

if(CONFIG_BOARD_BB9900)
    zephyr_library()
    zephyr_library_sources_ifdef(CONFIG_INPUT_A320 drivers/a320.c)
    zephyr_library_sources(trackpad_light.c)
endif()
