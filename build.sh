#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Compiling C++ engine..."

# Detect OS and set output name
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "mingw"* || "$OSTYPE" == "cygwin" ]]; then
    OUTPUT="libsnake.dll"
    g++ -std=c++17 -O2 -shared -static -o "$OUTPUT" cpp/engine.cpp
else
    OUTPUT="libsnake.so"
    g++ -std=c++17 -O2 -shared -fPIC -o "$OUTPUT" cpp/engine.cpp
fi

echo "Built $OUTPUT successfully."
