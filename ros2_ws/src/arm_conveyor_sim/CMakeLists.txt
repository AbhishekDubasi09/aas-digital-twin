cmake_minimum_required(VERSION 3.8)
project(arm_conveyor_sim)

find_package(ament_cmake REQUIRED)

install(DIRECTORY urdf worlds launch DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/cycle_manager.py DESTINATION lib/${PROJECT_NAME})

ament_package()
