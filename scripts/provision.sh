#!/usr/bin/env bash
set -Eeuo pipefail

DATA_SCIENCE_SIMULATOR_REPO="https://github.com/tidepool-org/data-science-simulator.git"
DATA_SCIENCE_SIMULATOR_COMMIT="2f486457c36a96331571bf355324d19cc99a900f"

LOOP_ALGORITHM_TO_PYTHON_REPO="https://github.com/tidepool-org/LoopAlgorithmToPython.git"
LOOP_ALGORITHM_TO_PYTHON_COMMIT="d555ca707dab46b42c9485a3925e263bb09e021a"

LOOP_ALGORITHM_REPO="https://github.com/tidepool-org/LoopAlgorithm.git"
LOOP_ALGORITHM_COMMIT="ab55554f72ac191a3698392b447f72117c02cc2d"

CONDA_ENV_NAME="${CONDA_ENV_NAME:-tidepool-data-science-simulator-swift}"
CONDA_SOLVER="${CONDA_SOLVER:-libmamba}"
SWIFT_VERSION="${SWIFT_VERSION:-6.0.3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPRO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
WORKSPACE_DIR="${WORKSPACE_DIR:-${REPRO_ROOT}/workspace}"
TOOLS_DIR_WAS_SET="${TOOLS_DIR+x}"
TOOLS_DIR="${TOOLS_DIR:-${WORKSPACE_DIR}/.toolchains}"
PROVISIONING_ASSETS_DIR="${REPRO_ROOT}/provisioning_assets"
SIMULATOR_LIBRARY_OVERRIDE_DIR="${PROVISIONING_ASSETS_DIR}/library_overrides/data-science-simulator/tidepool_data_science_simulator"
CONDA_LIBRARY_OVERRIDE_DIR="${PROVISIONING_ASSETS_DIR}/library_overrides/tidepool-data-science-models/tidepool_data_science_models"
PRESET_PROJECT_ASSETS_DIR="${PROVISIONING_ASSETS_DIR}/preset_validation/project"
PATCHES_DIR="${PROVISIONING_ASSETS_DIR}/patches"

CREATE_CONDA_ENV=1
BUILD_SWIFT_BRIDGE=1
INSTALL_SWIFT=auto
INSTALL_SYSTEM_DEPS="${INSTALL_SYSTEM_DEPS:-0}"
RECREATE_CONDA_ENV=0
RUN_TESTS=0
SMOKE_TEST=1

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Provision the pinned Tidepool simulator workspace.

Options:
  --workspace DIR          Clone/build under DIR (default: ${WORKSPACE_DIR})
  --skip-conda            Do not create/update the conda environment
  --recreate-conda        Remove and recreate the conda environment if it exists
  --skip-swift-build      Do not build LoopAlgorithmToPython dynamic library
  --skip-swift-install    Do not install Swift automatically on Linux
  --install-system-deps   On Ubuntu, install Swift runtime/build dependencies with apt
  --run-tests             Run pytest after provisioning
  --no-smoke-test         Skip the Python import/ctypes smoke test
  -h, --help              Show this help

Environment overrides:
  CONDA_ENV_NAME          Conda environment name (default: ${CONDA_ENV_NAME})
  CONDA_FRONTEND          Explicit conda-compatible executable to use
  CONDA_SOLVER            Solver to pass to conda env create/update (default: ${CONDA_SOLVER})
  SWIFT_VERSION           Swift toolchain to install on Linux (default: ${SWIFT_VERSION})
  WORKSPACE_DIR           Same as --workspace
  TOOLS_DIR               Local toolchain install directory
  INSTALL_SYSTEM_DEPS=1   Same as --install-system-deps
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

quote_path() {
  printf '%q' "$1"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --workspace)
        [ "$#" -ge 2 ] || die "--workspace requires a directory"
        WORKSPACE_DIR="$2"
        if [ -z "${TOOLS_DIR_WAS_SET}" ]; then
          TOOLS_DIR="${WORKSPACE_DIR}/.toolchains"
        fi
        shift 2
        ;;
      --skip-conda)
        CREATE_CONDA_ENV=0
        shift
        ;;
      --recreate-conda)
        RECREATE_CONDA_ENV=1
        shift
        ;;
      --skip-swift-build)
        BUILD_SWIFT_BRIDGE=0
        shift
        ;;
      --skip-swift-install)
        INSTALL_SWIFT=never
        shift
        ;;
      --install-system-deps)
        INSTALL_SYSTEM_DEPS=1
        shift
        ;;
      --run-tests)
        RUN_TESTS=1
        shift
        ;;
      --no-smoke-test)
        SMOKE_TEST=0
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown option: $1"
        ;;
    esac
  done

  WORKSPACE_DIR="$(mkdir -p "${WORKSPACE_DIR}" && cd "${WORKSPACE_DIR}" && pwd -P)"
  TOOLS_DIR="$(mkdir -p "${TOOLS_DIR}" && cd "${TOOLS_DIR}" && pwd -P)"
}

swift_version_is_supported() {
  case "$1" in
    6.*) return 0 ;;
    *) return 1 ;;
  esac
}

detect_swift_version() {
  swift --version 2>/dev/null | sed -n 's/.*Swift version \([0-9][0-9.]*\).*/\1/p' | head -n 1
}

ensure_command() {
  have "$1" || die "required command not found: $1"
}

ubuntu_platforms_for_swift() {
  [ -r /etc/os-release ] || die "Swift auto-install currently supports Ubuntu Linux only"
  # shellcheck disable=SC1091
  . /etc/os-release

  case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:22.04) printf 'ubuntu2204 ubuntu22.04\n' ;;
    ubuntu:20.04) printf 'ubuntu2004 ubuntu20.04\n' ;;
    *)
      die "Swift auto-install only knows Ubuntu 20.04/22.04. Install Swift ${SWIFT_VERSION}+ manually, or rerun with --skip-swift-install if swift is already available."
      ;;
  esac
}

maybe_install_ubuntu_swift_deps() {
  local python_lib

  [ "$(uname -s)" = "Linux" ] || return 0

  if [ "${INSTALL_SYSTEM_DEPS}" != "1" ]; then
    cat <<EOF

Swift on Linux may require OS packages such as clang, libcurl, libxml2, libz3,
sqlite, and zlib. If the Swift build fails because one is missing, rerun:

  INSTALL_SYSTEM_DEPS=1 $(quote_path "$0")

EOF
    return 0
  fi

  have apt-get || die "--install-system-deps requires apt-get"
  have sudo || die "--install-system-deps requires sudo"

  # shellcheck disable=SC1091
  . /etc/os-release
  case "${VERSION_ID:-}" in
    22.04) python_lib="libpython3.10" ;;
    20.04) python_lib="libpython3.8" ;;
    *) python_lib="python3-dev" ;;
  esac

  log "Installing Ubuntu build/runtime dependencies for Swift"
  sudo apt-get update
  sudo apt-get install -y \
    binutils \
    clang \
    curl \
    git \
    libcurl4-openssl-dev \
    libedit2 \
    "${python_lib}" \
    libsqlite3-0 \
    libxml2-dev \
    libz3-dev \
    pkg-config \
    python3 \
    tzdata \
    zlib1g-dev
}

prepend_swift_runtime_paths() {
  local swift_bin swift_root linux_runtime macos_runtime

  swift_bin="$(command -v swift || true)"
  [ -n "${swift_bin}" ] || return 0
  swift_root="$(cd "$(dirname "${swift_bin}")/.." && pwd -P)"
  linux_runtime="${swift_root}/lib/swift/linux"
  macos_runtime="${swift_root}/lib/swift/macosx"

  if [ -d "${linux_runtime}" ]; then
    export LD_LIBRARY_PATH="${linux_runtime}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  fi

  if [ -d "${macos_runtime}" ]; then
    export DYLD_LIBRARY_PATH="${macos_runtime}${DYLD_LIBRARY_PATH:+:${DYLD_LIBRARY_PATH}}"
  fi
}

prepend_workspace_swift_paths() {
  local swift_link linux_runtime macos_runtime
  swift_link="${TOOLS_DIR}/swift"

  if [ -x "${swift_link}/usr/bin/swift" ]; then
    export PATH="${swift_link}/usr/bin:${PATH}"
  fi

  linux_runtime="${swift_link}/usr/lib/swift/linux"
  macos_runtime="${swift_link}/usr/lib/swift/macosx"

  if [ -d "${linux_runtime}" ]; then
    export LD_LIBRARY_PATH="${linux_runtime}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  fi

  if [ -d "${macos_runtime}" ]; then
    export DYLD_LIBRARY_PATH="${macos_runtime}${DYLD_LIBRARY_PATH:+:${DYLD_LIBRARY_PATH}}"
  fi
}

install_swift_linux() {
  [ "${INSTALL_SWIFT}" != "never" ] || die "Swift is required to build the Swift bridge"

  local os_name arch url_platform archive_platform release archive url tmp_dir extract_dir swift_link
  os_name="$(uname -s)"
  [ "${os_name}" = "Linux" ] || die "Swift not found. On macOS, install Xcode or Xcode Command Line Tools, then rerun."

  arch="$(uname -m)"
  [ "${arch}" = "x86_64" ] || die "Swift auto-install currently supports Linux x86_64 only; found ${arch}"

  read -r url_platform archive_platform < <(ubuntu_platforms_for_swift)
  release="swift-${SWIFT_VERSION}-RELEASE"
  archive="${release}-${archive_platform}.tar.gz"
  url="https://download.swift.org/swift-${SWIFT_VERSION}-release/${url_platform}/${release}/${archive}"
  extract_dir="${TOOLS_DIR}/${release}-${archive_platform}"
  swift_link="${TOOLS_DIR}/swift"

  maybe_install_ubuntu_swift_deps
  ensure_command curl

  if [ ! -x "${extract_dir}/usr/bin/swift" ]; then
    log "Downloading Swift ${SWIFT_VERSION} for ${archive_platform}"
    tmp_dir="$(mktemp -d)"
    curl -fL "${url}" -o "${tmp_dir}/${archive}"

    log "Installing Swift into ${extract_dir}"
    mkdir -p "${TOOLS_DIR}"
    tar -xzf "${tmp_dir}/${archive}" -C "${TOOLS_DIR}"
    rm -rf "${tmp_dir}"
  fi

  ln -sfn "${extract_dir}" "${swift_link}"
  export PATH="${swift_link}/usr/bin:${PATH}"
  prepend_swift_runtime_paths
}

ensure_swift() {
  local version

  drop_stale_workspace_swift_link

  if have swift; then
    version="$(detect_swift_version || true)"
    if [ -n "${version}" ] && swift_version_is_supported "${version}"; then
      log "Using Swift ${version} at $(command -v swift)"
      prepend_swift_runtime_paths
      return 0
    fi

    printf 'Found Swift at %s, but version "%s" may not satisfy Package.swift tools 6.0.\n' "$(command -v swift)" "${version:-unknown}" >&2
  fi

  install_swift_linux

  version="$(detect_swift_version || true)"
  [ -n "${version}" ] || die "Swift installation completed, but swift --version did not report a version"
  swift_version_is_supported "${version}" || die "Swift ${version} is too old; need Swift 6.0 or newer"
  log "Using Swift ${version} at $(command -v swift)"
}

# The activation helper and smoke test put ${TOOLS_DIR}/swift first on PATH and
# LD_LIBRARY_PATH. If that link still points at an older toolchain (e.g. 5.10.1
# from before the LoopAlgorithm upgrade) while the bridge was built with a newer
# Swift found elsewhere, the library would load a mismatched Swift runtime.
drop_stale_workspace_swift_link() {
  local swift_link version
  swift_link="${TOOLS_DIR}/swift"

  [ -L "${swift_link}" ] || return 0
  [ -x "${swift_link}/usr/bin/swift" ] || return 0
  version="$("${swift_link}/usr/bin/swift" --version 2>/dev/null | sed -n 's/.*Swift version \([0-9][0-9.]*\).*/\1/p' | head -n 1)"
  swift_version_is_supported "${version}" && return 0

  log "Unlinking unsupported workspace Swift ${version:-unknown} at ${swift_link}"
  rm "${swift_link}"
}

clone_at_commit() {
  local name repo_url commit path actual
  name="$1"
  repo_url="$2"
  commit="$3"
  path="$4"

  if [ -e "${path}" ] && [ ! -d "${path}/.git" ]; then
    die "${path} exists but is not a git checkout"
  fi

  if [ ! -d "${path}/.git" ]; then
    log "Cloning ${name}"
    git clone "${repo_url}" "${path}"
  fi

  git -C "${path}" remote set-url origin "${repo_url}"

  # Provisioning patches checkouts in place, so an existing checkout of an older
  # pin is dirty with those patches and cannot be moved to the new commit.
  if [ "$(git -C "${path}" rev-parse HEAD)" != "${commit}" ] && [ -n "$(git -C "${path}" status --porcelain)" ]; then
    die "${path} has local changes and is not at the pinned commit ${commit}. Remove it (rm -rf $(quote_path "${path}")) to re-clone, or rerun with a fresh --workspace."
  fi

  log "Checking out ${name} at ${commit}"
  git -C "${path}" fetch --tags --prune origin
  git -C "${path}" checkout --detach "${commit}"
  actual="$(git -C "${path}" rev-parse HEAD)"
  [ "${actual}" = "${commit}" ] || die "${name} checkout mismatch: expected ${commit}, got ${actual}"
}

patch_loop_algorithm_dependency() {
  local bridge_dir package_file tmp_file
  bridge_dir="$1"
  package_file="${bridge_dir}/Package.swift"

  grep -q 'https://github.com/tidepool-org/LoopAlgorithm.git' "${package_file}" || {
    grep -q '\.package(path: "../LoopAlgorithm")' "${package_file}" && return 0
    die "could not find LoopAlgorithm dependency line in ${package_file}"
  }

  log "Pointing LoopAlgorithmToPython at the local pinned LoopAlgorithm checkout"
  tmp_file="$(mktemp)"
  awk '
    /https:\/\/github.com\/tidepool-org\/LoopAlgorithm\.git/ {
      print "        .package(path: \"../LoopAlgorithm\"),"
      next
    }
    { print }
  ' "${package_file}" > "${tmp_file}"
  mv "${tmp_file}" "${package_file}"
}

patch_simulator_setup_for_editable_install() {
  local simulator_dir setup_file tmp_file
  simulator_dir="$1"
  setup_file="${simulator_dir}/setup.py"

  [ -f "${setup_file}" ] || return 0
  grep -q "tidepool_data_science_simulator.vizualization" "${setup_file}" || return 0

  log "Patching simulator setup.py package typo for editable install"
  tmp_file="$(mktemp)"
  awk '
    /tidepool_data_science_simulator\.vizualization/ {
      sub(/vizualization/, "visualization")
    }
    { print }
  ' "${setup_file}" > "${tmp_file}"
  mv "${tmp_file}" "${setup_file}"
}

copy_required_file() {
  local src dest
  src="$1"
  dest="$2"

  [ -f "${src}" ] || die "missing source file: ${src}"
  [ -f "${dest}" ] || die "missing destination file to replace: ${dest}"
  cp "${src}" "${dest}"
}

copy_asset_file() {
  local src dest
  src="$1"
  dest="$2"

  [ -f "${src}" ] || die "missing source file: ${src}"
  cp "${src}" "${dest}"
}

patch_presets_measure_support() {
  local simulator_dir measures_file
  simulator_dir="$1"
  measures_file="${simulator_dir}/tidepool_data_science_simulator/models/measures.py"

  grep -q '^class PhysicalActivity' "${measures_file}" && grep -q '^class HeartRateTrace' "${measures_file}" && return 0

  log "Adding preset physical-activity measures"
  cat >> "${measures_file}" <<'PY'


class PhysicalActivity(object):
    def __init__(self, activity, duration):
        self.activity = activity
        self.duration = int(duration)

    def __repr__(self):
        return "{} {}min".format(self.activity, self.duration)


class HeartRateTrace(object):
    def __init__(self, datetimes=None, values=None):
        self.datetimes = datetimes or []
        self.hr_values = values or []
        self._hr_by_datetime = dict(zip(self.datetimes, self.hr_values))

    def get_heart_rate(self, time):
        return self._hr_by_datetime.get(time, 0)
PY
}

patch_presets_event_support() {
  local simulator_dir events_file
  simulator_dir="$1"
  events_file="${simulator_dir}/tidepool_data_science_simulator/models/events.py"

  grep -q '^class PhysicalActivityTimeline' "${events_file}" && return 0

  log "Adding preset physical-activity timeline"
  cat >> "${events_file}" <<'PY'


from tidepool_data_science_simulator.models.measures import PhysicalActivity


class PhysicalActivityTimeline(EventTimeline):
    def __init__(self, datetimes=None, events=None):
        super().__init__(datetimes, events)
        self.event_type = PhysicalActivity
PY
}

patch_presets_patient_config_support() {
  local simulator_dir parser_file tmp_file
  simulator_dir="$1"
  parser_file="${simulator_dir}/tidepool_data_science_simulator/makedata/scenario_parser.py"

  grep -q 'pa_timeline=None' "${parser_file}" && return 0

  log "Adding preset physical-activity field to PatientConfig"
  tmp_file="$(mktemp)"
  awk '
    /        action_timeline,/ {
      print
      print "        pa_timeline=None,"
      next
    }
    /        self.action_timeline = action_timeline/ {
      print
      print "        self.pa_timeline = pa_timeline"
      next
    }
    { print }
  ' "${parser_file}" > "${tmp_file}"
  mv "${tmp_file}" "${parser_file}"
}

patch_schedule_override_window_support() {
  local simulator_dir simulation_file tmp_file
  simulator_dir="$1"
  simulation_file="${simulator_dir}/tidepool_data_science_simulator/models/simulation.py"

  grep -q 'override_end_time = getattr(self, "override_end_time", None)' "${simulation_file}" && return 0

  log "Adding bounded preset override support"
  tmp_file="$(mktemp)"
  awk '
    /    def set_override\(self, percentage_change\):/ {
      in_set_override = 1
      print
      next
    }
    in_set_override && /    def unset_override\(self\):/ {
      in_set_override = 0
      print
      next
    }
    in_set_override && /        for \(start_time, end_time\), setting in self.schedule.items\(\):/ {
      print "        override_end_time = getattr(self, \"override_end_time\", None)"
      print
      print "            if override_end_time is not None and end_time > override_end_time:"
      print "                continue"
      next
    }
    { print }
  ' "${simulation_file}" > "${tmp_file}"
  mv "${tmp_file}" "${simulation_file}"
}

patch_presets_controller_defaults() {
  local simulator_dir controller_file tmp_file
  simulator_dir="$1"
  controller_file="${simulator_dir}/tidepool_data_science_simulator/makedata/make_controller.py"

  grep -q '"maximum_autobolus": None' "${controller_file}" && grep -q '"partial_application_factor": 0.4' "${controller_file}" && return 0

  log "Setting preset controller defaults"
  tmp_file="$(mktemp)"
  awk '
    /"maximum_autobolus": 0\.0,/ {
      sub(/0\.0/, "None")
    }
    /"partial_application_factor": None,/ {
      sub(/None/, "0.4")
    }
    /"partial_application_factor": 0\.0,/ {
      sub(/0\.0/, "0.4")
    }
    { print }
  ' "${controller_file}" > "${tmp_file}"
  mv "${tmp_file}" "${controller_file}"
}

patch_presets_supporting_types() {
  local simulator_dir
  simulator_dir="$1"

  patch_presets_measure_support "${simulator_dir}"
  patch_presets_event_support "${simulator_dir}"
  patch_presets_patient_config_support "${simulator_dir}"
  patch_schedule_override_window_support "${simulator_dir}"
  patch_presets_controller_defaults "${simulator_dir}"
}

replace_simulator_library_scripts() {
  local simulator_dir
  simulator_dir="$1"

  log "Replacing simulator library scripts from ${SIMULATOR_LIBRARY_OVERRIDE_DIR}"
  copy_required_file "${SIMULATOR_LIBRARY_OVERRIDE_DIR}/models/patient.py" "${simulator_dir}/tidepool_data_science_simulator/models/patient.py"
  copy_required_file "${SIMULATOR_LIBRARY_OVERRIDE_DIR}/makedata/make_patient.py" "${simulator_dir}/tidepool_data_science_simulator/makedata/make_patient.py"
  copy_required_file "${SIMULATOR_LIBRARY_OVERRIDE_DIR}/models/swift_controller.py" "${simulator_dir}/tidepool_data_science_simulator/models/swift_controller.py"
  patch_presets_supporting_types "${simulator_dir}"
}

conda_site_packages_dir() {
  local conda_bin
  conda_bin="$1"

  "${conda_bin}" run -n "${CONDA_ENV_NAME}" python -c 'import site; paths = site.getsitepackages(); print(next((path for path in paths if path.endswith("site-packages")), paths[0]))'
}

replace_conda_library_scripts() {
  local conda_bin site_packages model_dir
  conda_bin="$(find_conda_frontend)"
  site_packages="$(conda_site_packages_dir "${conda_bin}")"
  model_dir="${site_packages}/tidepool_data_science_models/models"

  log "Replacing conda library scripts in ${model_dir}"
  copy_required_file "${CONDA_LIBRARY_OVERRIDE_DIR}/models/treatment_models.py" "${model_dir}/treatment_models.py"
  copy_required_file "${CONDA_LIBRARY_OVERRIDE_DIR}/models/simple_metabolism_model.py" "${model_dir}/simple_metabolism_model.py"
}

copy_preset_project_assets() {
  local simulator_dir presets_dir
  simulator_dir="$1"
  presets_dir="${simulator_dir}/tidepool_data_science_simulator/projects/presets"

  log "Copying preset validation project assets"
  mkdir -p "${presets_dir}"
  copy_asset_file "${PRESET_PROJECT_ASSETS_DIR}/t1dexi_preset_validation.py" "${presets_dir}/t1dexi_preset_validation.py"
  copy_asset_file "${PRESET_PROJECT_ASSETS_DIR}/tidepool_helmsley_preset_virtual_patients.csv" "${presets_dir}/tidepool_helmsley_preset_virtual_patients.csv"
  copy_asset_file "${PRESET_PROJECT_ASSETS_DIR}/param_values.py" "${presets_dir}/param_values.py"
}

apply_patch_once() {
  local repo_dir patch_file
  repo_dir="$1"
  patch_file="$2"

  [ -f "${patch_file}" ] || die "missing patch file: ${patch_file}"

  if git -C "${repo_dir}" apply --reverse --check "${patch_file}" >/dev/null 2>&1; then
    return 0
  fi

  log "Applying $(basename "${patch_file}")"
  git -C "${repo_dir}" apply "${patch_file}" || die "$(basename "${patch_file}") no longer applies to ${repo_dir}; update it for the pinned commit"
}

patch_swift_sources() {
  local loop_algorithm_dir bridge_dir
  loop_algorithm_dir="$1"
  bridge_dir="$2"

  apply_patch_once "${bridge_dir}" "${PATCHES_DIR}/LoopAlgorithmToPython-loop-quantity-port.patch"

  if [ "$(uname -s)" = "Linux" ]; then
    apply_patch_once "${loop_algorithm_dir}" "${PATCHES_DIR}/LoopAlgorithm-linux-swift5-language-mode.patch"
  fi
}

build_swift_bridge() {
  local bridge_dir loop_algorithm_dir lib_ext built_lib target_lib dylib_compat
  bridge_dir="$1"
  loop_algorithm_dir="$2"

  ensure_swift
  patch_loop_algorithm_dependency "${bridge_dir}"
  patch_swift_sources "${loop_algorithm_dir}" "${bridge_dir}"

  log "Building LoopAlgorithmToPython dynamic library"
  (
    cd "${bridge_dir}"
    swift package clean
    swift package resolve
    swift build --configuration release
  )

  case "$(uname -s)" in
    Darwin) lib_ext="dylib" ;;
    Linux) lib_ext="so" ;;
    *) die "unsupported OS for dynamic library copy: $(uname -s)" ;;
  esac

  built_lib="${bridge_dir}/.build/release/libLoopAlgorithmToPython.${lib_ext}"
  if [ ! -f "${built_lib}" ]; then
    built_lib="$(find "${bridge_dir}/.build" -path "*/release/libLoopAlgorithmToPython.${lib_ext}" -type f -print -quit)"
  fi

  [ -n "${built_lib}" ] && [ -f "${built_lib}" ] || die "Swift build finished, but libLoopAlgorithmToPython.${lib_ext} was not found"

  target_lib="${bridge_dir}/loop_to_python_api/libLoopAlgorithmToPython.${lib_ext}"
  cp "${built_lib}" "${target_lib}"

  if [ "${lib_ext}" = "so" ]; then
    dylib_compat="${bridge_dir}/loop_to_python_api/libLoopAlgorithmToPython.dylib"
    ln -sfn "libLoopAlgorithmToPython.so" "${dylib_compat}"
  fi
}

find_conda_frontend() {
  if [ -n "${CONDA_FRONTEND:-}" ]; then
    have "${CONDA_FRONTEND}" || die "CONDA_FRONTEND is set but not found: ${CONDA_FRONTEND}"
    command -v "${CONDA_FRONTEND}"
  elif have conda; then
    command -v conda
  elif have micromamba; then
    command -v micromamba
  elif have mamba; then
    command -v mamba
  else
    die "conda/mamba/micromamba not found. Install Miniconda or Miniforge, then rerun."
  fi
}

is_conda_frontend() {
  [ "$(basename "$1")" = "conda" ]
}

conda_supports_solver() {
  local conda_bin solver
  conda_bin="$1"
  solver="$2"

  "${conda_bin}" env create --help 2>&1 | grep -Eq -- "--solver \{[^}]*${solver}[^}]*\}"
}

ensure_conda_solver_available() {
  local conda_bin
  conda_bin="$1"

  is_conda_frontend "${conda_bin}" || return 0
  [ -n "${CONDA_SOLVER}" ] || return 0

  if ! conda_supports_solver "${conda_bin}" "${CONDA_SOLVER}"; then
    die "conda at ${conda_bin} does not advertise solver '${CONDA_SOLVER}'. Install the official conda-libmamba-solver package into base, or rerun with CONDA_SOLVER=classic."
  fi
}

conda_solver_args() {
  local conda_bin
  conda_bin="$1"

  if is_conda_frontend "${conda_bin}" && [ -n "${CONDA_SOLVER}" ]; then
    printf '%s\n' --solver "${CONDA_SOLVER}"
  fi
}

conda_env_exists() {
  local conda_bin
  conda_bin="$1"
  "${conda_bin}" env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -qx "${CONDA_ENV_NAME}"
}

create_or_update_conda_env() {
  local sim_dir conda_bin env_file
  local -a solver_args=()
  sim_dir="$1"
  conda_bin="$(find_conda_frontend)"
  env_file="${sim_dir}/conda-environment-swift.yml"

  [ -f "${env_file}" ] || die "missing conda environment file: ${env_file}"

  ensure_conda_solver_available "${conda_bin}"
  mapfile -t solver_args < <(conda_solver_args "${conda_bin}")

  if is_conda_frontend "${conda_bin}" && [ -n "${CONDA_SOLVER}" ]; then
    log "Using conda with ${CONDA_SOLVER} solver"
  fi

  if [ "${RECREATE_CONDA_ENV}" = "1" ] && conda_env_exists "${conda_bin}"; then
    log "Removing existing conda environment ${CONDA_ENV_NAME}"
    "${conda_bin}" env remove -n "${CONDA_ENV_NAME}" -y
  fi

  if conda_env_exists "${conda_bin}"; then
    log "Updating conda environment ${CONDA_ENV_NAME}"
    (cd "${sim_dir}" && "${conda_bin}" env update "${solver_args[@]}" -n "${CONDA_ENV_NAME}" -f "${env_file}" --prune)
  else
    log "Creating conda environment ${CONDA_ENV_NAME}"
    (cd "${sim_dir}" && "${conda_bin}" env create "${solver_args[@]}" -f "${env_file}")
  fi

  log "Installing simulator checkout editable into ${CONDA_ENV_NAME}"
  "${conda_bin}" run -n "${CONDA_ENV_NAME}" python -m pip install -e "${sim_dir}"
}

run_smoke_test() {
  local sim_dir conda_bin
  local -a run_output_args=()
  sim_dir="$1"
  conda_bin="$(find_conda_frontend)"

  prepend_workspace_swift_paths
  if is_conda_frontend "${conda_bin}"; then
    run_output_args=(--no-capture-output)
  fi

  log "Running Python smoke test"
  (
    cd "${sim_dir}"
    "${conda_bin}" run "${run_output_args[@]}" -n "${CONDA_ENV_NAME}" python -c 'import tidepool_data_science_simulator; from loop_to_python_api.api import percent_absorption_at_percent_time; value = percent_absorption_at_percent_time(0.5); print(f"smoke test ok: Swift bridge returned {value}")'
  )
}

run_pytest() {
  local sim_dir conda_bin
  sim_dir="$1"
  conda_bin="$(find_conda_frontend)"

  log "Running pytest"
  (cd "${sim_dir}" && "${conda_bin}" run -n "${CONDA_ENV_NAME}" pytest)
}

write_activation_helper() {
  local helper
  helper="${WORKSPACE_DIR}/activate-simulator.sh"

  cat > "${helper}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR=$(quote_path "${WORKSPACE_DIR}")
CONDA_ENV_NAME=$(quote_path "${CONDA_ENV_NAME}")
SWIFT_LINK="\${WORKSPACE_DIR}/.toolchains/swift"

if [ -x "\${SWIFT_LINK}/usr/bin/swift" ]; then
  export PATH="\${SWIFT_LINK}/usr/bin:\${PATH}"
fi

if [ -d "\${SWIFT_LINK}/usr/lib/swift/linux" ]; then
  export LD_LIBRARY_PATH="\${SWIFT_LINK}/usr/lib/swift/linux\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}"
fi

if [ -d "\${SWIFT_LINK}/usr/lib/swift/macosx" ]; then
  export DYLD_LIBRARY_PATH="\${SWIFT_LINK}/usr/lib/swift/macosx\${DYLD_LIBRARY_PATH:+:\${DYLD_LIBRARY_PATH}}"
fi

if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "\$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "\${CONDA_ENV_NAME}"
else
  echo "conda is not on PATH; activate ${CONDA_ENV_NAME} manually." >&2
fi
EOF

  chmod +x "${helper}"
}

write_manifest() {
  local manifest
  manifest="${WORKSPACE_DIR}/provisioned-commits.txt"

  cat > "${manifest}" <<EOF
data-science-simulator ${DATA_SCIENCE_SIMULATOR_COMMIT} ${DATA_SCIENCE_SIMULATOR_REPO}
LoopAlgorithmToPython ${LOOP_ALGORITHM_TO_PYTHON_COMMIT} ${LOOP_ALGORITHM_TO_PYTHON_REPO}
LoopAlgorithm ${LOOP_ALGORITHM_COMMIT} ${LOOP_ALGORITHM_REPO}
EOF
}

main() {
  parse_args "$@"
  ensure_command git

  local simulator_dir bridge_dir loop_algorithm_dir
  simulator_dir="${WORKSPACE_DIR}/data-science-simulator"
  bridge_dir="${WORKSPACE_DIR}/LoopAlgorithmToPython"
  loop_algorithm_dir="${WORKSPACE_DIR}/LoopAlgorithm"

  log "Provisioning workspace at ${WORKSPACE_DIR}"
  clone_at_commit "data-science-simulator" "${DATA_SCIENCE_SIMULATOR_REPO}" "${DATA_SCIENCE_SIMULATOR_COMMIT}" "${simulator_dir}"
  clone_at_commit "LoopAlgorithmToPython" "${LOOP_ALGORITHM_TO_PYTHON_REPO}" "${LOOP_ALGORITHM_TO_PYTHON_COMMIT}" "${bridge_dir}"
  clone_at_commit "LoopAlgorithm" "${LOOP_ALGORITHM_REPO}" "${LOOP_ALGORITHM_COMMIT}" "${loop_algorithm_dir}"
  patch_simulator_setup_for_editable_install "${simulator_dir}"
  replace_simulator_library_scripts "${simulator_dir}"
  copy_preset_project_assets "${simulator_dir}"

  if [ "${BUILD_SWIFT_BRIDGE}" = "1" ]; then
    build_swift_bridge "${bridge_dir}" "${loop_algorithm_dir}"
  fi

  if [ "${CREATE_CONDA_ENV}" = "1" ]; then
    create_or_update_conda_env "${simulator_dir}"
    replace_conda_library_scripts
  fi

  write_activation_helper
  write_manifest

  if [ "${CREATE_CONDA_ENV}" = "1" ] && [ "${SMOKE_TEST}" = "1" ]; then
    run_smoke_test "${simulator_dir}"
  fi

  if [ "${CREATE_CONDA_ENV}" = "1" ] && [ "${RUN_TESTS}" = "1" ]; then
    run_pytest "${simulator_dir}"
  fi

  cat <<EOF

Provisioning complete.

Pinned checkouts:
  ${simulator_dir}
  ${bridge_dir}
  ${loop_algorithm_dir}

Activate with:
  source $(quote_path "${WORKSPACE_DIR}/activate-simulator.sh")
EOF
}

main "$@"
