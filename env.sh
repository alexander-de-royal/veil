# Tools a macOS build needs on PATH:  source env.sh
# GNU sed and GNU patch because LibreWolf's scripts assume Linux versions
# (brew install gnu-sed gpatch); Python 3.13 and Rust from `mach bootstrap`.
export PATH="$HOME/.cargo/bin:$HOME/.local/share/uv/python/cpython-3.13-macos-aarch64-none/bin:/opt/homebrew/opt/gnu-sed/libexec/gnubin:/opt/homebrew/opt/gpatch/libexec/gnubin:$PATH"
export MOZBUILD_STATE_PATH="$HOME/.mozbuild"
