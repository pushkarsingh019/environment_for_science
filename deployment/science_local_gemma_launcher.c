#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L

/*
 * Independent, statically linked process boundary for scored local Gemma.
 *
 * Production builds deliberately have no command-line configuration.  The
 * launcher reads two fixed secret files, validates the non-secret environment,
 * verifies the separately staged bootstrap, and replaces itself with the one
 * approved Python command and a newly allocated exact environment.
 */

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef __linux__
#include <elf.h>
#include <sys/auxv.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#endif

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

#ifndef O_DIRECTORY
#define O_DIRECTORY 0
#endif

#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#ifndef SCIENCE_LOCAL_GEMMA_PYTHON_PATH
#define SCIENCE_LOCAL_GEMMA_PYTHON_PATH "/usr/bin/python3.12"
#endif

#ifndef SCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH
#define SCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH                                      \
    "/approved/ro/release/science_local_gemma_bootstrap.py"
#endif

#ifndef SCIENCE_LOCAL_GEMMA_SECRET_DIRECTORY
#define SCIENCE_LOCAL_GEMMA_SECRET_DIRECTORY "/run/secrets"
#endif

#define SCIENCE_API_SECRET_NAME "science-local-gemma-api-key"
#define SCIENCE_ATTESTATION_SECRET_NAME "science-local-gemma-attestation-key"
#define SCIENCE_SECRET_MIN_BYTES 32U
#define SCIENCE_SECRET_MAX_BYTES 4096U
#define SCIENCE_RUNTIME_UID ((uid_t)65532U)
#define SCIENCE_RUNTIME_GID ((gid_t)65532U)

enum value_kind {
    VALUE_ABSOLUTE_PATH,
    VALUE_CUDA_VERSION,
    VALUE_CUDA_VISIBLE_DEVICES,
    VALUE_SHA256,
    VALUE_IMAGE_DIGEST,
};

struct setting {
    const char *name;
    enum value_kind kind;
    int required;
    const char *value;
};

static struct setting settings[] = {
    {"CUDA_HOME", VALUE_ABSOLUTE_PATH, 0, NULL},
    {"CUDA_PATH", VALUE_ABSOLUTE_PATH, 0, NULL},
    {"CUDA_VISIBLE_DEVICES", VALUE_CUDA_VISIBLE_DEVICES, 0, NULL},
    {"SCIENCE_LOCAL_GEMMA_CUDA_VERSION", VALUE_CUDA_VERSION, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_MODEL_ROOT", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256", VALUE_SHA256, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256", VALUE_SHA256, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_RENDERER_ROOT", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST", VALUE_IMAGE_DIGEST, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_TORCH_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256", VALUE_SHA256, 1, NULL},
    {"SCIENCE_LOCAL_GEMMA_VLLM_WHEEL", VALUE_ABSOLUTE_PATH, 1, NULL},
};

static const size_t setting_count = sizeof(settings) / sizeof(settings[0]);

struct sha256_context {
    uint8_t block[64];
    uint32_t state[8];
    uint64_t total_bits;
    size_t block_length;
};

static const uint32_t sha256_constants[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU,
    0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U, 0xd807aa98U, 0x12835b01U,
    0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U,
    0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U,
    0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U,
    0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
    0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U,
    0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U, 0x1e376c08U,
    0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU,
    0x682e6ff3U, 0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

static void write_stderr(const char *message, size_t length) {
    while (length > 0U) {
        ssize_t written = write(STDERR_FILENO, message, length);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return;
        }
        message += (size_t)written;
        length -= (size_t)written;
    }
}

static int fail(const char *message) {
    static const char prefix[] = "science-local-gemma-launcher: ";
    write_stderr(prefix, sizeof(prefix) - 1U);
    write_stderr(message, strlen(message));
    write_stderr("\n", 1U);
    return 70;
}

static void secure_zero(void *pointer, size_t length) {
    volatile unsigned char *bytes = (volatile unsigned char *)pointer;
    while (length > 0U) {
        *bytes = 0U;
        ++bytes;
        --length;
    }
}

static uint32_t rotate_right(uint32_t value, unsigned int count) {
    return (value >> count) | (value << (32U - count));
}

static void sha256_transform(struct sha256_context *context) {
    uint32_t words[64];
    uint32_t a;
    uint32_t b;
    uint32_t c;
    uint32_t d;
    uint32_t e;
    uint32_t f;
    uint32_t g;
    uint32_t h;
    size_t index;

    for (index = 0U; index < 16U; ++index) {
        size_t offset = index * 4U;
        words[index] = ((uint32_t)context->block[offset] << 24U) |
                       ((uint32_t)context->block[offset + 1U] << 16U) |
                       ((uint32_t)context->block[offset + 2U] << 8U) |
                       (uint32_t)context->block[offset + 3U];
    }
    for (index = 16U; index < 64U; ++index) {
        uint32_t s0 = rotate_right(words[index - 15U], 7U) ^
                      rotate_right(words[index - 15U], 18U) ^
                      (words[index - 15U] >> 3U);
        uint32_t s1 = rotate_right(words[index - 2U], 17U) ^
                      rotate_right(words[index - 2U], 19U) ^
                      (words[index - 2U] >> 10U);
        words[index] = words[index - 16U] + s0 + words[index - 7U] + s1;
    }

    a = context->state[0];
    b = context->state[1];
    c = context->state[2];
    d = context->state[3];
    e = context->state[4];
    f = context->state[5];
    g = context->state[6];
    h = context->state[7];
    for (index = 0U; index < 64U; ++index) {
        uint32_t sum1 = rotate_right(e, 6U) ^ rotate_right(e, 11U) ^
                        rotate_right(e, 25U);
        uint32_t choice = (e & f) ^ ((~e) & g);
        uint32_t temporary1 = h + sum1 + choice + sha256_constants[index] +
                              words[index];
        uint32_t sum0 = rotate_right(a, 2U) ^ rotate_right(a, 13U) ^
                        rotate_right(a, 22U);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temporary2 = sum0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary1;
        d = c;
        c = b;
        b = a;
        a = temporary1 + temporary2;
    }
    context->state[0] += a;
    context->state[1] += b;
    context->state[2] += c;
    context->state[3] += d;
    context->state[4] += e;
    context->state[5] += f;
    context->state[6] += g;
    context->state[7] += h;
}

static void sha256_initialize(struct sha256_context *context) {
    memset(context, 0, sizeof(*context));
    context->state[0] = 0x6a09e667U;
    context->state[1] = 0xbb67ae85U;
    context->state[2] = 0x3c6ef372U;
    context->state[3] = 0xa54ff53aU;
    context->state[4] = 0x510e527fU;
    context->state[5] = 0x9b05688cU;
    context->state[6] = 0x1f83d9abU;
    context->state[7] = 0x5be0cd19U;
}

static void sha256_update(
    struct sha256_context *context,
    const uint8_t *bytes,
    size_t length
) {
    size_t index;
    for (index = 0U; index < length; ++index) {
        context->block[context->block_length] = bytes[index];
        ++context->block_length;
        if (context->block_length == sizeof(context->block)) {
            sha256_transform(context);
            context->total_bits += 512U;
            context->block_length = 0U;
        }
    }
}

static void sha256_finalize(struct sha256_context *context, uint8_t digest[32]) {
    size_t index = context->block_length;
    uint64_t total_bits = context->total_bits + (uint64_t)index * 8U;

    context->block[index++] = 0x80U;
    if (index > 56U) {
        while (index < 64U) {
            context->block[index++] = 0U;
        }
        sha256_transform(context);
        index = 0U;
    }
    while (index < 56U) {
        context->block[index++] = 0U;
    }
    for (index = 0U; index < 8U; ++index) {
        context->block[63U - index] = (uint8_t)(total_bits >> (index * 8U));
    }
    sha256_transform(context);
    for (index = 0U; index < 8U; ++index) {
        digest[index * 4U] = (uint8_t)(context->state[index] >> 24U);
        digest[index * 4U + 1U] = (uint8_t)(context->state[index] >> 16U);
        digest[index * 4U + 2U] = (uint8_t)(context->state[index] >> 8U);
        digest[index * 4U + 3U] = (uint8_t)context->state[index];
    }
    secure_zero(context, sizeof(*context));
}

static int has_prefix(const char *value, const char *prefix) {
    return strncmp(value, prefix, strlen(prefix)) == 0;
}

static int is_lower_hex(const char *value, size_t length) {
    size_t index;
    if (strlen(value) != length) {
        return 0;
    }
    for (index = 0U; index < length; ++index) {
        if (!((value[index] >= '0' && value[index] <= '9') ||
              (value[index] >= 'a' && value[index] <= 'f'))) {
            return 0;
        }
    }
    return 1;
}

static int is_absolute_normalized_path(const char *value) {
    const char *component;
    const char *cursor;
    size_t length = strlen(value);

    if (length == 0U || length >= PATH_MAX || value[0] != '/') {
        return 0;
    }
    if (length > 1U && value[length - 1U] == '/') {
        return 0;
    }
    for (cursor = value; *cursor != '\0'; ++cursor) {
        unsigned char byte = (unsigned char)*cursor;
        if (byte < 0x21U || byte > 0x7eU || byte == '\\' || byte == '=') {
            return 0;
        }
        if (*cursor == '/' && cursor[1] == '/') {
            return 0;
        }
    }
    component = value + 1;
    while (*component != '\0') {
        const char *separator = strchr(component, '/');
        size_t component_length = separator == NULL
                                      ? strlen(component)
                                      : (size_t)(separator - component);
        if ((component_length == 1U && component[0] == '.') ||
            (component_length == 2U && component[0] == '.' &&
             component[1] == '.')) {
            return 0;
        }
        if (separator == NULL) {
            break;
        }
        component = separator + 1;
    }
    return 1;
}

static int is_cuda_visible_devices(const char *value) {
    size_t index;
    int preceding_comma = 1;
    size_t length = strlen(value);
    if (length == 0U || length > 32U) {
        return 0;
    }
    for (index = 0U; index < length; ++index) {
        if (value[index] == ',') {
            if (preceding_comma) {
                return 0;
            }
            preceding_comma = 1;
        } else if (value[index] >= '0' && value[index] <= '9') {
            preceding_comma = 0;
        } else {
            return 0;
        }
    }
    return !preceding_comma;
}

static int validate_setting(const struct setting *setting) {
    switch (setting->kind) {
        case VALUE_ABSOLUTE_PATH:
            return is_absolute_normalized_path(setting->value);
        case VALUE_CUDA_VERSION:
            return strcmp(setting->value, "12.9") == 0;
        case VALUE_CUDA_VISIBLE_DEVICES:
            return is_cuda_visible_devices(setting->value);
        case VALUE_SHA256:
            return is_lower_hex(setting->value, 64U);
        case VALUE_IMAGE_DIGEST:
            return has_prefix(setting->value, "sha256:") &&
                   is_lower_hex(setting->value + 7U, 64U);
    }
    return 0;
}

static struct setting *find_setting(const char *name, size_t name_length) {
    size_t index;
    for (index = 0U; index < setting_count; ++index) {
        if (strlen(settings[index].name) == name_length &&
            memcmp(settings[index].name, name, name_length) == 0) {
            return &settings[index];
        }
    }
    return NULL;
}

static int is_name(const char *name, size_t length, const char *expected) {
    return strlen(expected) == length && memcmp(name, expected, length) == 0;
}

static int is_discarded_container_setting(const char *name, size_t length) {
    return is_name(name, length, "HOME") || is_name(name, length, "HOSTNAME") ||
           is_name(name, length, "PATH") || is_name(name, length, "LANG") ||
           is_name(name, length, "LC_ALL") ||
           (length >= 3U && memcmp(name, "LC_", 3U) == 0) ||
           is_name(name, length, "NVIDIA_VISIBLE_DEVICES") ||
           is_name(name, length, "NVIDIA_DRIVER_CAPABILITIES");
}

static int parse_environment(char *const environment[]) {
    size_t environment_index;
    size_t setting_index;

    for (environment_index = 0U; environment[environment_index] != NULL;
         ++environment_index) {
        const char *entry = environment[environment_index];
        const char *equals = strchr(entry, '=');
        size_t name_length;
        struct setting *setting;
        if (equals == NULL || equals == entry) {
            return fail("environment entry is malformed");
        }
        name_length = (size_t)(equals - entry);
        if (is_name(entry, name_length, "SCIENCE_LOCAL_GEMMA_API_KEY") ||
            is_name(entry, name_length, "SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY")) {
            return fail("runtime secrets must come from the fixed secret files");
        }
        if ((name_length >= 3U && memcmp(entry, "LD_", 3U) == 0) ||
            (name_length >= 5U && memcmp(entry, "DYLD_", 5U) == 0) ||
            (name_length >= 6U && memcmp(entry, "PYTHON", 6U) == 0)) {
            return fail("interpreter or loader injection environment is forbidden");
        }
        setting = find_setting(entry, name_length);
        if (setting != NULL) {
            if (setting->value != NULL) {
                return fail("approved environment setting is duplicated");
            }
            setting->value = equals + 1;
            if (!validate_setting(setting)) {
                return fail("approved environment setting is invalid");
            }
            continue;
        }
        if ((name_length >= strlen("SCIENCE_LOCAL_GEMMA_") &&
             memcmp(entry, "SCIENCE_LOCAL_GEMMA_", strlen("SCIENCE_LOCAL_GEMMA_")) ==
                 0) ||
            (name_length >= 5U && memcmp(entry, "CUDA_", 5U) == 0)) {
            return fail("undeclared serving environment setting is forbidden");
        }
        if (!is_discarded_container_setting(entry, name_length)) {
            return fail("undeclared launcher environment setting is forbidden");
        }
    }
    for (setting_index = 0U; setting_index < setting_count; ++setting_index) {
        if (settings[setting_index].required && settings[setting_index].value == NULL) {
            return fail("required serving environment setting is missing");
        }
    }
    return 0;
}

static int validate_fixed_file(const char *path, int must_be_executable) {
    struct stat metadata;
    char resolved[PATH_MAX];
    if (!is_absolute_normalized_path(path) || lstat(path, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode)) {
        return fail("approved executable artifact is not a regular file");
    }
    if ((metadata.st_mode & (S_IWGRP | S_IWOTH)) != 0 ||
        (must_be_executable && (metadata.st_mode & S_IXUSR) == 0)) {
        return fail("approved executable artifact permissions are unsafe");
    }
#ifndef SCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING
    if (metadata.st_uid != 0) {
        return fail("approved executable artifact is not root owned");
    }
#endif
    if (realpath(path, resolved) == NULL || strcmp(path, resolved) != 0) {
        return fail("approved executable artifact path is not canonical");
    }
    return 0;
}

static int hash_bootstrap(char output[65]) {
    int descriptor;
    struct stat metadata;
    struct sha256_context context;
    uint8_t digest[32];
    uint8_t buffer[65536];
    ssize_t received;
    size_t index;

    descriptor = open(
        SCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH,
        O_RDONLY | O_CLOEXEC | O_NOFOLLOW
    );
    if (descriptor < 0 || fstat(descriptor, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode)) {
        if (descriptor >= 0) {
            (void)close(descriptor);
        }
        return fail("trusted bootstrap could not be opened safely");
    }
    sha256_initialize(&context);
    while ((received = read(descriptor, buffer, sizeof(buffer))) > 0) {
        sha256_update(&context, buffer, (size_t)received);
    }
    if (received < 0 || close(descriptor) != 0) {
        secure_zero(&context, sizeof(context));
        return fail("trusted bootstrap could not be hashed");
    }
    sha256_finalize(&context, digest);
    for (index = 0U; index < sizeof(digest); ++index) {
        static const char alphabet[] = "0123456789abcdef";
        output[index * 2U] = alphabet[digest[index] >> 4U];
        output[index * 2U + 1U] = alphabet[digest[index] & 0x0fU];
    }
    output[64] = '\0';
    secure_zero(digest, sizeof(digest));
    secure_zero(buffer, sizeof(buffer));
    return 0;
}

static int validate_secret_directory(int descriptor) {
    struct stat path_metadata;
    struct stat metadata;
    if (lstat(SCIENCE_LOCAL_GEMMA_SECRET_DIRECTORY, &path_metadata) != 0 ||
        !S_ISDIR(path_metadata.st_mode) || descriptor < 0 ||
        fstat(descriptor, &metadata) != 0 ||
        !S_ISDIR(metadata.st_mode) ||
        path_metadata.st_dev != metadata.st_dev ||
        path_metadata.st_ino != metadata.st_ino ||
        (metadata.st_mode & (S_IWGRP | S_IWOTH)) != 0) {
        return fail("fixed secret directory is unsafe");
    }
#ifndef SCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING
    if (metadata.st_uid != 0) {
        return fail("fixed secret directory is not root owned");
    }
#endif
    return 0;
}

static int secret_metadata_unchanged(
    const struct stat *before,
    const struct stat *after
) {
    if (before->st_dev != after->st_dev || before->st_ino != after->st_ino ||
        before->st_mode != after->st_mode || before->st_uid != after->st_uid ||
        before->st_gid != after->st_gid || before->st_nlink != after->st_nlink ||
        before->st_size != after->st_size) {
        return 0;
    }
#ifdef __APPLE__
    return before->st_mtimespec.tv_sec == after->st_mtimespec.tv_sec &&
           before->st_mtimespec.tv_nsec == after->st_mtimespec.tv_nsec &&
           before->st_ctimespec.tv_sec == after->st_ctimespec.tv_sec &&
           before->st_ctimespec.tv_nsec == after->st_ctimespec.tv_nsec;
#else
    return before->st_mtim.tv_sec == after->st_mtim.tv_sec &&
           before->st_mtim.tv_nsec == after->st_mtim.tv_nsec &&
           before->st_ctim.tv_sec == after->st_ctim.tv_sec &&
           before->st_ctim.tv_nsec == after->st_ctim.tv_nsec;
#endif
}

static int read_secret(int directory, const char *name, char **output, size_t *length) {
    int descriptor = -1;
    struct stat path_metadata;
    struct stat before;
    struct stat after;
    char *value = NULL;
    size_t offset = 0U;
    ssize_t received;
    size_t index;

    if (fstatat(directory, name, &path_metadata, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISREG(path_metadata.st_mode)) {
        return fail("runtime secret file identity or permissions are invalid");
    }
    descriptor = openat(directory, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0 || fstat(descriptor, &before) != 0 ||
        !S_ISREG(before.st_mode) || before.st_uid != geteuid() ||
        path_metadata.st_dev != before.st_dev ||
        path_metadata.st_ino != before.st_ino ||
        (before.st_mode & 07777U) != S_IRUSR || before.st_nlink != 1 ||
        before.st_size < (off_t)SCIENCE_SECRET_MIN_BYTES ||
        before.st_size > (off_t)SCIENCE_SECRET_MAX_BYTES) {
        if (descriptor >= 0) {
            (void)close(descriptor);
        }
        return fail("runtime secret file identity or permissions are invalid");
    }
    value = (char *)malloc((size_t)before.st_size + 1U);
    if (value == NULL) {
        (void)close(descriptor);
        return fail("runtime secret allocation failed");
    }
    while (offset < (size_t)before.st_size) {
        received = read(descriptor, value + offset, (size_t)before.st_size - offset);
        if (received <= 0) {
            secure_zero(value, (size_t)before.st_size + 1U);
            free(value);
            (void)close(descriptor);
            return fail("runtime secret file changed while being read");
        }
        offset += (size_t)received;
    }
    received = read(descriptor, value + offset, 1U);
    if (received != 0 || fstat(descriptor, &after) != 0 ||
        !secret_metadata_unchanged(&before, &after) || close(descriptor) != 0) {
        secure_zero(value, (size_t)before.st_size + 1U);
        free(value);
        return fail("runtime secret file changed while being read");
    }
    for (index = 0U; index < offset; ++index) {
        unsigned char byte = (unsigned char)value[index];
        if (byte < 0x21U || byte > 0x7eU) {
            secure_zero(value, offset + 1U);
            free(value);
            return fail("runtime secret must be one unambiguous printable ASCII value");
        }
    }
    value[offset] = '\0';
    *output = value;
    *length = offset;
    return 0;
}

static int secrets_are_distinct(
    const char *left,
    size_t left_length,
    const char *right,
    size_t right_length
) {
    size_t maximum = left_length > right_length ? left_length : right_length;
    size_t index;
    unsigned int difference = (unsigned int)(left_length ^ right_length);
    for (index = 0U; index < maximum; ++index) {
        unsigned char left_byte = index < left_length ? (unsigned char)left[index] : 0U;
        unsigned char right_byte =
            index < right_length ? (unsigned char)right[index] : 0U;
        difference |= (unsigned int)(left_byte ^ right_byte);
    }
    return difference != 0U;
}

static char *environment_entry(const char *name, const char *value) {
    size_t name_length = strlen(name);
    size_t value_length = strlen(value);
    char *entry;
    if (name_length > SIZE_MAX - value_length - 2U) {
        return NULL;
    }
    entry = (char *)malloc(name_length + value_length + 2U);
    if (entry == NULL) {
        return NULL;
    }
    memcpy(entry, name, name_length);
    entry[name_length] = '=';
    memcpy(entry + name_length + 1U, value, value_length + 1U);
    return entry;
}

#if defined(__linux__) || defined(SCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING)
static int runtime_identity_is_approved(
    uid_t real_uid,
    uid_t effective_uid,
    gid_t real_gid,
    gid_t effective_gid,
    const gid_t *supplementary_groups,
    size_t supplementary_group_count
) {
    return real_uid == SCIENCE_RUNTIME_UID &&
           effective_uid == SCIENCE_RUNTIME_UID &&
           real_gid == SCIENCE_RUNTIME_GID &&
           effective_gid == SCIENCE_RUNTIME_GID &&
           supplementary_group_count == 1U &&
           supplementary_groups != NULL &&
           supplementary_groups[0] == SCIENCE_RUNTIME_GID;
}
#endif

static int harden_process(void) {
    struct rlimit no_core = {0U, 0U};
    (void)no_core;
    (void)umask(077U);
#ifndef SCIENCE_LOCAL_GEMMA_LAUNCHER_TESTING
#ifndef __linux__
    return fail("production launcher requires Linux");
#else
    gid_t supplementary_groups[1];
    int supplementary_group_count = getgroups(0, NULL);
    if (getauxval(AT_BASE) != 0U) {
        return fail("production launcher must have no dynamic interpreter");
    }
    if (supplementary_group_count != 1 ||
        getgroups(1, supplementary_groups) != 1 ||
        !runtime_identity_is_approved(
            getuid(),
            geteuid(),
            getgid(),
            getegid(),
            supplementary_groups,
            1U
        )) {
        return fail("production launcher requires the exact approved runtime identity");
    }
    if (setrlimit(RLIMIT_CORE, &no_core) != 0 ||
        prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        return fail("production process hardening failed");
    }
#endif
#else
    (void)runtime_identity_is_approved;
#endif
    return 0;
}

static int close_inherited_descriptors(void) {
#if defined(__linux__) && defined(SYS_close_range)
    if (syscall(SYS_close_range, 3U, ~0U, 0U) == 0) {
        return 0;
    }
    if (errno != ENOSYS && errno != EINVAL) {
        return fail("inherited process descriptors could not be closed");
    }
#endif
    {
        long limit = sysconf(_SC_OPEN_MAX);
        int descriptor;
        if (limit < 0 || limit > 1048576L) {
            limit = 1048576L;
        }
        for (descriptor = 3; descriptor < (int)limit; ++descriptor) {
            (void)close(descriptor);
        }
    }
    return 0;
}

static const char *setting_value(const char *name) {
    struct setting *setting = find_setting(name, strlen(name));
    return setting == NULL ? NULL : setting->value;
}

int main(int argc, char *argv[], char *environment[]) {
    int status;
    int secret_directory = -1;
    char *api_secret = NULL;
    char *attestation_secret = NULL;
    size_t api_secret_length = 0U;
    size_t attestation_secret_length = 0U;
    char bootstrap_digest[65];
    char **child_environment = NULL;
    size_t child_environment_count = 0U;
    size_t child_index = 0U;
    size_t index;
    const char *model_root;
    char *child_arguments[36];

    (void)argv;
    if (argc != 1) {
        return fail("launcher accepts no command-line arguments");
    }
    status = harden_process();
    if (status != 0) {
        return status;
    }
    status = parse_environment(environment);
    if (status != 0) {
        return status;
    }
    status = validate_fixed_file(SCIENCE_LOCAL_GEMMA_PYTHON_PATH, 1);
    if (status != 0) {
        return status;
    }
    status = validate_fixed_file(SCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH, 0);
    if (status != 0) {
        return status;
    }
    status = hash_bootstrap(bootstrap_digest);
    if (status != 0 || strcmp(
                           bootstrap_digest,
                           setting_value("SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256")
                       ) != 0) {
        secure_zero(bootstrap_digest, sizeof(bootstrap_digest));
        return fail("trusted bootstrap digest does not match its external pin");
    }
    secure_zero(bootstrap_digest, sizeof(bootstrap_digest));

    secret_directory = open(
        SCIENCE_LOCAL_GEMMA_SECRET_DIRECTORY,
        O_RDONLY | O_CLOEXEC | O_DIRECTORY | O_NOFOLLOW
    );
    status = validate_secret_directory(secret_directory);
    if (status != 0) {
        if (secret_directory >= 0) {
            (void)close(secret_directory);
        }
        return status;
    }
    status = read_secret(
        secret_directory,
        SCIENCE_API_SECRET_NAME,
        &api_secret,
        &api_secret_length
    );
    if (status == 0) {
        status = read_secret(
            secret_directory,
            SCIENCE_ATTESTATION_SECRET_NAME,
            &attestation_secret,
            &attestation_secret_length
        );
    }
    (void)close(secret_directory);
    if (status != 0) {
        if (api_secret != NULL) {
            secure_zero(api_secret, api_secret_length + 1U);
            free(api_secret);
        }
        return status;
    }
    if (!secrets_are_distinct(
            api_secret,
            api_secret_length,
            attestation_secret,
            attestation_secret_length
        )) {
        secure_zero(api_secret, api_secret_length + 1U);
        secure_zero(attestation_secret, attestation_secret_length + 1U);
        free(api_secret);
        free(attestation_secret);
        return fail("runtime API and attestation secrets must be distinct");
    }

    child_environment_count = 1U;
    for (index = 0U; index < setting_count; ++index) {
        if (settings[index].value != NULL) {
            ++child_environment_count;
        }
    }
    child_environment =
        (char **)calloc(child_environment_count + 1U, sizeof(*child_environment));
    if (child_environment == NULL) {
        status = fail("child environment allocation failed");
        goto cleanup;
    }
    child_environment[child_index++] = environment_entry("LC_ALL", "C");
    for (index = 0U; index < setting_count; ++index) {
        if (settings[index].value != NULL) {
            child_environment[child_index++] =
                environment_entry(settings[index].name, settings[index].value);
        }
    }
    for (index = 0U; index < child_environment_count; ++index) {
        if (child_environment[index] == NULL) {
            status = fail("child environment allocation failed");
            goto cleanup;
        }
    }

    model_root = setting_value("SCIENCE_LOCAL_GEMMA_MODEL_ROOT");
    {
        char *approved[] = {
            (char *)SCIENCE_LOCAL_GEMMA_PYTHON_PATH,
            "-I",
            "-S",
            "-B",
            (char *)SCIENCE_LOCAL_GEMMA_BOOTSTRAP_PATH,
            "serve",
            (char *)model_root,
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--served-model-name",
            "google/gemma-4-E4B-it",
            "--dtype",
            "bfloat16",
            "--max-model-len",
            "32768",
            "--tensor-parallel-size",
            "1",
            "--gpu-memory-utilization",
            "0.35",
            "--enforce-eager",
            "--max-num-seqs",
            "16",
            "--generation-config",
            "vllm",
            "--tool-call-parser",
            "gemma4",
            "--enable-auto-tool-choice",
            "--disable-log-requests",
            "--limit-mm-per-prompt",
            "{\"image\":0,\"audio\":0,\"video\":0}",
            "--middleware",
            "studio.policy_evaluation.gemma_attestation:local_gemma_attestation_middleware",
            NULL,
        };
        memcpy(child_arguments, approved, sizeof(approved));
    }
    secure_zero(api_secret, api_secret_length + 1U);
    secure_zero(attestation_secret, attestation_secret_length + 1U);
    free(api_secret);
    free(attestation_secret);
    api_secret = NULL;
    attestation_secret = NULL;
    api_secret_length = 0U;
    attestation_secret_length = 0U;
    status = close_inherited_descriptors();
    if (status != 0) {
        goto cleanup;
    }
    execve(
        SCIENCE_LOCAL_GEMMA_PYTHON_PATH,
        child_arguments,
        child_environment
    );
    status = fail("approved Python process could not be executed");

cleanup:
    if (api_secret != NULL) {
        secure_zero(api_secret, api_secret_length + 1U);
        free(api_secret);
    }
    if (attestation_secret != NULL) {
        secure_zero(attestation_secret, attestation_secret_length + 1U);
        free(attestation_secret);
    }
    if (child_environment != NULL) {
        for (index = 0U; index < child_environment_count; ++index) {
            if (child_environment[index] != NULL) {
                secure_zero(child_environment[index], strlen(child_environment[index]));
                free(child_environment[index]);
            }
        }
        free(child_environment);
    }
    return status;
}
