# Board-specific code: the trackpad sensor driver, the trackpad light, and the
# scroll-mode pieces (direction processor + toggle behavior, Caps Lock glue).
# Zephyr picks this file up from the board directory.

if(CONFIG_BOARD_BB9900)
    zephyr_library()
    zephyr_library_include_directories(${CMAKE_CURRENT_SOURCE_DIR})
    # ZMK's own headers (zmk/*.h, drivers/behavior.h, drivers/input_processor.h)
    zephyr_library_include_directories(${CMAKE_SOURCE_DIR}/include)
    zephyr_library_sources_ifdef(CONFIG_INPUT_A320 drivers/a320.c)
    zephyr_library_sources(trackpad_light.c)
    zephyr_library_sources(scroll_dir.c)
    zephyr_library_sources(behavior_scroll_dir_toggle.c)
    zephyr_library_sources_ifdef(CONFIG_UC9900_CAPS_SCROLL caps_scroll.c)
endif()
