#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>
#else
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#endif

#define RATE 136
#define PAD_POS (RATE - 1)
#define ROUNDS 23
#define MAX_DIGITS 20
#define MAX_THREADS 1024
#define MAX_INPUT 8192
#define MAX_SALT 4095
#define MAX_DIFFICULTY 2000000000LL
#define TIME_BUDGET_SEC 45.0
#define TIME_CHECK_STRIDE 4096
#define WORK_BLOCK 4096

static _Atomic int g_found = 0;
static _Atomic long long g_deadline_ms = -1;
static _Atomic uint64_t g_next = 0;
static _Atomic uint64_t g_limit = 0;
static _Atomic uint64_t g_best = UINT64_MAX;

static const uint64_t RC[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808aULL,
    0x8000000080008000ULL, 0x000000000000808bULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008aULL,
    0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000aULL,
    0x000000008000808bULL, 0x800000000000008bULL, 0x8000000000008089ULL,
    0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800aULL, 0x800000008000000aULL, 0x8000000080008081ULL,
    0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL,
};

static inline uint64_t rol64(uint64_t x, int n) {
  n &= 63;
  if (n == 0)
    return x;
  return (x << n) | (x >> (64 - n));
}

#define KECCAK_ROUND(rc)                                                       \
  do {                                                                         \
    uint64_t c0, c1, c2, c3, c4, d0, d1, d2, d3, d4;                           \
    uint64_t p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12;           \
    uint64_t p13, p14, p15, p16, p17, p18, p19, p20, p21, p22, p23, p24;       \
    c0 = A00 ^ A01 ^ A02 ^ A03 ^ A04;                                          \
    c1 = A10 ^ A11 ^ A12 ^ A13 ^ A14;                                          \
    c2 = A20 ^ A21 ^ A22 ^ A23 ^ A24;                                          \
    c3 = A30 ^ A31 ^ A32 ^ A33 ^ A34;                                          \
    c4 = A40 ^ A41 ^ A42 ^ A43 ^ A44;                                          \
    d0 = c4 ^ rol64(c1, 1);                                                    \
    d1 = c0 ^ rol64(c2, 1);                                                    \
    d2 = c1 ^ rol64(c3, 1);                                                    \
    d3 = c2 ^ rol64(c4, 1);                                                    \
    d4 = c3 ^ rol64(c0, 1);                                                    \
    A00 ^= d0; A01 ^= d0; A02 ^= d0; A03 ^= d0; A04 ^= d0;                     \
    A10 ^= d1; A11 ^= d1; A12 ^= d1; A13 ^= d1; A14 ^= d1;                     \
    A20 ^= d2; A21 ^= d2; A22 ^= d2; A23 ^= d2; A24 ^= d2;                     \
    A30 ^= d3; A31 ^= d3; A32 ^= d3; A33 ^= d3; A34 ^= d3;                     \
    A40 ^= d4; A41 ^= d4; A42 ^= d4; A43 ^= d4; A44 ^= d4;                     \
    p0 = A00;                                                                  \
    p1 = rol64(A11, 44);                                                       \
    p2 = rol64(A22, 43);                                                       \
    p3 = rol64(A33, 21);                                                       \
    p4 = rol64(A44, 14);                                                       \
    p5 = rol64(A30, 28);                                                       \
    p6 = rol64(A41, 20);                                                       \
    p7 = rol64(A02, 3);                                                        \
    p8 = rol64(A13, 45);                                                       \
    p9 = rol64(A24, 61);                                                       \
    p10 = rol64(A10, 1);                                                       \
    p11 = rol64(A21, 6);                                                       \
    p12 = rol64(A32, 25);                                                      \
    p13 = rol64(A43, 8);                                                       \
    p14 = rol64(A04, 18);                                                      \
    p15 = rol64(A40, 27);                                                      \
    p16 = rol64(A01, 36);                                                      \
    p17 = rol64(A12, 10);                                                      \
    p18 = rol64(A23, 15);                                                      \
    p19 = rol64(A34, 56);                                                      \
    p20 = rol64(A20, 62);                                                      \
    p21 = rol64(A31, 55);                                                      \
    p22 = rol64(A42, 39);                                                      \
    p23 = rol64(A03, 41);                                                      \
    p24 = rol64(A14, 2);                                                       \
    A00 = p0 ^ ((~p1) & p2);                                                   \
    A10 = p1 ^ ((~p2) & p3);                                                   \
    A20 = p2 ^ ((~p3) & p4);                                                   \
    A30 = p3 ^ ((~p4) & p0);                                                   \
    A40 = p4 ^ ((~p0) & p1);                                                   \
    A01 = p5 ^ ((~p6) & p7);                                                   \
    A11 = p6 ^ ((~p7) & p8);                                                   \
    A21 = p7 ^ ((~p8) & p9);                                                   \
    A31 = p8 ^ ((~p9) & p5);                                                   \
    A41 = p9 ^ ((~p5) & p6);                                                   \
    A02 = p10 ^ ((~p11) & p12);                                                \
    A12 = p11 ^ ((~p12) & p13);                                                \
    A22 = p12 ^ ((~p13) & p14);                                                \
    A32 = p13 ^ ((~p14) & p10);                                                \
    A42 = p14 ^ ((~p10) & p11);                                                \
    A03 = p15 ^ ((~p16) & p17);                                                \
    A13 = p16 ^ ((~p17) & p18);                                                \
    A23 = p17 ^ ((~p18) & p19);                                                \
    A33 = p18 ^ ((~p19) & p15);                                                \
    A43 = p19 ^ ((~p15) & p16);                                                \
    A04 = p20 ^ ((~p21) & p22);                                                \
    A14 = p21 ^ ((~p22) & p23);                                                \
    A24 = p22 ^ ((~p23) & p24);                                                \
    A34 = p23 ^ ((~p24) & p20);                                                \
    A44 = p24 ^ ((~p20) & p21);                                                \
    A00 ^= (rc);                                                               \
  } while (0)

static void keccak_f(uint64_t *s) {
  uint64_t A00 = s[0], A10 = s[1], A20 = s[2], A30 = s[3], A40 = s[4];
  uint64_t A01 = s[5], A11 = s[6], A21 = s[7], A31 = s[8], A41 = s[9];
  uint64_t A02 = s[10], A12 = s[11], A22 = s[12], A32 = s[13], A42 = s[14];
  uint64_t A03 = s[15], A13 = s[16], A23 = s[17], A33 = s[18], A43 = s[19];
  uint64_t A04 = s[20], A14 = s[21], A24 = s[22], A34 = s[23], A44 = s[24];
  KECCAK_ROUND(RC[1]);
  KECCAK_ROUND(RC[2]);
  KECCAK_ROUND(RC[3]);
  KECCAK_ROUND(RC[4]);
  KECCAK_ROUND(RC[5]);
  KECCAK_ROUND(RC[6]);
  KECCAK_ROUND(RC[7]);
  KECCAK_ROUND(RC[8]);
  KECCAK_ROUND(RC[9]);
  KECCAK_ROUND(RC[10]);
  KECCAK_ROUND(RC[11]);
  KECCAK_ROUND(RC[12]);
  KECCAK_ROUND(RC[13]);
  KECCAK_ROUND(RC[14]);
  KECCAK_ROUND(RC[15]);
  KECCAK_ROUND(RC[16]);
  KECCAK_ROUND(RC[17]);
  KECCAK_ROUND(RC[18]);
  KECCAK_ROUND(RC[19]);
  KECCAK_ROUND(RC[20]);
  KECCAK_ROUND(RC[21]);
  KECCAK_ROUND(RC[22]);
  KECCAK_ROUND(RC[23]);
  s[0] = A00; s[1] = A10; s[2] = A20; s[3] = A30; s[4] = A40;
  s[5] = A01; s[6] = A11; s[7] = A21; s[8] = A31; s[9] = A41;
  s[10] = A02; s[11] = A12; s[12] = A22; s[13] = A32; s[14] = A42;
  s[15] = A03; s[16] = A13; s[17] = A23; s[18] = A33; s[19] = A43;
  s[20] = A04; s[21] = A14; s[22] = A24; s[23] = A34; s[24] = A44;
}

static void absorb_prefix(uint64_t st[25], const uint8_t *prefix, size_t len) {
  memset(st, 0, 25 * sizeof(uint64_t));
  size_t off = 0;
  while (len - off >= RATE) {
    for (size_t i = 0; i < RATE; i += 8) {
      uint64_t w = 0;
      for (int b = 0; b < 8; b++)
        w |= (uint64_t)prefix[off + i + b] << (8 * b);
      st[i / 8] ^= w;
    }
    keccak_f(st);
    off += RATE;
  }
  for (size_t i = 0; i < len - off; i++)
    st[i / 8] ^= (uint64_t)prefix[off + i] << (8 * (i % 8));
}

static int to_digits(uint64_t v, char *buf) {
  char tmp[MAX_DIGITS];
  int n = 0;
  do {
    if (n >= MAX_DIGITS)
      return -1;
    tmp[n++] = (char)('0' + (int)(v % 10));
    v /= 10;
  } while (v > 0);
  for (int i = 0; i < n; i++)
    buf[i] = tmp[n - 1 - i];
  buf[n] = '\0';
  return n;
}

static void inc_digits(char *buf, int *dlen) {
  if (*dlen < 1 || *dlen >= MAX_DIGITS)
    return;
  int i = *dlen - 1;
  while (i >= 0 && buf[i] == '9') {
    buf[i] = '0';
    i--;
  }
  if (i < 0) {
    buf[0] = '1';
    for (int j = 1; j <= *dlen; j++)
      buf[j] = '0';
    (*dlen)++;
    buf[*dlen] = '\0';
  } else {
    buf[i]++;
  }
}

static int check_counter(const uint64_t base[25], size_t off0,
                         const char *digits, int dlen,
                         const uint8_t target[32]) {
  uint64_t st[25];
  memcpy(st, base, sizeof(st));
  size_t off = off0;
  for (int i = 0; i < dlen; i++) {
    st[off >> 3] ^= (uint64_t)(uint8_t)digits[i] << (8 * (off & 7));
    off++;
    if (off == RATE) {
      keccak_f(st);
      off = 0;
    }
  }
  st[off >> 3] ^= (uint64_t)0x06 << (8 * (off & 7));
  if (++off == RATE)
    keccak_f(st);
  st[PAD_POS >> 3] ^= (uint64_t)0x80 << (8 * (PAD_POS & 7));
  keccak_f(st);
  for (int i = 0; i < 32; i++) {
    uint64_t lane = st[i >> 3];
    if ((uint8_t)((lane >> (8 * (i & 7))) & 0xffu) != target[i])
      return 0;
  }
  return 1;
}

static const uint64_t *g_base;
static size_t g_off0;
static const uint8_t *g_target;

static long long now_ms(void) {
#if defined(_WIN32)
  return (long long)GetTickCount64();
#else
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
#endif
}

static int budget_exhausted(void) {
  long long deadline = atomic_load(&g_deadline_ms);
  if (deadline < 0)
    return 0;
  return now_ms() >= deadline;
}

static void run_worker(void) {
  char digits[MAX_DIGITS + 1];
  for (;;) {
    if (atomic_load(&g_found))
      return;
    uint64_t limit = atomic_load(&g_limit);
    uint64_t start = atomic_fetch_add(&g_next, WORK_BLOCK);
    if (start >= limit)
      return;
    uint64_t end = start + WORK_BLOCK;
    if (end > limit)
      end = limit;
    int dlen = to_digits(start, digits);
    if (dlen < 0)
      continue;
    uint64_t stride = 0;
    for (uint64_t c = start; c < end; c++) {
      if (atomic_load(&g_found))
        return;
      if (++stride >= TIME_CHECK_STRIDE) {
        stride = 0;
        if (budget_exhausted()) {
          atomic_store(&g_found, 1);
          return;
        }
      }
      if (check_counter(g_base, g_off0, digits, dlen, g_target)) {
        uint64_t cur = atomic_load(&g_best);
        while (c < cur) {
          if (atomic_compare_exchange_weak(&g_best, &cur, c))
            break;
        }
        atomic_store(&g_found, 1);
        return;
      }
      inc_digits(digits, &dlen);
    }
  }
}

#if defined(_WIN32)
static DWORD WINAPI worker(LPVOID arg) {
  (void)arg;
  run_worker();
  return 0;
}
#else
static void *worker(void *arg) {
  (void)arg;
  run_worker();
  return NULL;
}
#endif

static int detect_threads(void) {
#if defined(_WIN32)
  SYSTEM_INFO si;
  GetSystemInfo(&si);
  int n = (int)si.dwNumberOfProcessors;
  return n > 0 ? n : 1;
#else
  long n = sysconf(_SC_NPROCESSORS_ONLN);
  return n > 0 ? (int)n : 1;
#endif
}

static int hex_to_bytes(const char *hex, uint8_t *out) {
  size_t n = strlen(hex);
  if (n % 2 || n > 64)
    return -1;
  for (size_t i = 0; i < n; i += 2) {
    int hi = hex[i], lo = hex[i + 1];
    int hv = (hi >= '0' && hi <= '9')   ? hi - '0'
             : (hi >= 'a' && hi <= 'f') ? hi - 'a' + 10
             : (hi >= 'A' && hi <= 'F') ? hi - 'A' + 10
                                        : -1;
    int lv = (lo >= '0' && lo <= '9')   ? lo - '0'
             : (lo >= 'a' && lo <= 'f') ? lo - 'a' + 10
             : (lo >= 'A' && lo <= 'F') ? lo - 'A' + 10
                                        : -1;
    if (hv < 0 || lv < 0)
      return -1;
    out[i / 2] = (uint8_t)((hv << 4) | lv);
  }
  return (int)(n / 2);
}

static const char *find_json_str(const char *json, const char *key, char *buf,
                                 size_t bufsz) {
  char pat[64];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char *p = strstr(json, pat);
  if (!p)
    return NULL;
  p = strchr(p + strlen(pat), ':');
  if (!p)
    return NULL;
  p++;
  while (*p == ' ' || *p == '\t')
    p++;
  if (*p != '"')
    return NULL;
  p++;
  size_t i = 0;
  while (*p && *p != '"') {
    if (i + 1 >= bufsz)
      return NULL;
    buf[i++] = *p++;
  }
  if (*p != '"')
    return NULL;
  buf[i] = '\0';
  return buf;
}

static long long find_json_ll(const char *json, const char *key) {
  char pat[64];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char *p = strstr(json, pat);
  if (!p)
    return -1;
  p = strchr(p + strlen(pat), ':');
  if (!p)
    return -1;
  p++;
  while (*p == ' ' || *p == '\t')
    p++;
  if (*p == '"')
    p++;
  return strtoll(p, NULL, 10);
}

int main(void) {
  char input[MAX_INPUT];
  size_t n = fread(input, 1, sizeof(input) - 1, stdin);
  if (ferror(stdin)) {
    puts("{\"error\":\"stdin read failed\"}");
    return 1;
  }
  input[n] = '\0';
  if (n >= sizeof(input) - 1) {
    puts("{\"error\":\"input too large\"}");
    return 1;
  }

  char challenge[128] = {0}, salt[MAX_SALT + 1] = {0};
  if (!find_json_str(input, "challenge", challenge, sizeof(challenge)) ||
      !find_json_str(input, "salt", salt, sizeof(salt))) {
    puts("{\"error\":\"missing challenge/salt\"}");
    return 1;
  }
  long long expire_at = find_json_ll(input, "expire_at");
  long long difficulty = find_json_ll(input, "difficulty");
  if (expire_at < 0 || difficulty <= 0) {
    puts("{\"error\":\"bad expire_at/difficulty\"}");
    return 1;
  }

  uint8_t target[32];
  if (hex_to_bytes(challenge, target) != 32) {
    puts("{\"error\":\"bad challenge hex\"}");
    return 1;
  }

  char prefix[4120];
  int plen = snprintf(prefix, sizeof(prefix), "%s_%lld_", salt, expire_at);
  if (plen < 0 || (size_t)plen >= sizeof(prefix)) {
    puts("{\"error\":\"salt too long\"}");
    return 1;
  }

  uint64_t base[25];
  absorb_prefix(base, (const uint8_t *)prefix, (size_t)plen);
  size_t off0 = (size_t)plen % RATE;

  uint64_t limit = difficulty < MAX_DIFFICULTY ? (uint64_t)difficulty
                                               : (uint64_t)MAX_DIFFICULTY;
  if (limit == 0) {
    puts("{\"error\":\"answer not found in range\"}");
    return 1;
  }

  atomic_store(&g_deadline_ms,
               now_ms() + (long long)(TIME_BUDGET_SEC * 1000.0));

  int nthreads = detect_threads();
  const char *env = getenv("POW_SOLVER_THREADS");
  if (env && env[0]) {
    char *end = NULL;
    long v = strtol(env, &end, 10);
    if (end != env && end != NULL && *end == '\0' && v > 0 && v <= MAX_THREADS)
      nthreads = (int)v;
  }
  if (nthreads > MAX_THREADS)
    nthreads = MAX_THREADS;
#if defined(_WIN32)
  if (nthreads > 64)
    nthreads = 64;
#endif
  if ((uint64_t)nthreads > limit)
    nthreads = (int)limit;
  if (nthreads < 1)
    nthreads = 1;

#if defined(_WIN32)
  HANDLE *threads = (HANDLE *)calloc((size_t)nthreads, sizeof(HANDLE));
#else
  pthread_t *threads = (pthread_t *)calloc((size_t)nthreads, sizeof(pthread_t));
#endif
  unsigned char *created = (unsigned char *)calloc((size_t)nthreads, 1);
  if (!threads || !created) {
    free(threads);
    free(created);
    puts("{\"error\":\"out of memory\"}");
    return 1;
  }

  g_base = base;
  g_off0 = off0;
  g_target = target;
  atomic_store(&g_limit, limit);
  atomic_store(&g_next, 0);
  atomic_store(&g_best, UINT64_MAX);
  atomic_store(&g_found, 0);

  for (int i = 0; i < nthreads; i++) {
    created[i] = 0;
#if defined(_WIN32)
    threads[i] = CreateThread(NULL, 0, worker, NULL, 0, NULL);
    if (threads[i])
      created[i] = 1;
    else
      run_worker();
#else
    if (!pthread_create(&threads[i], NULL, worker, NULL))
      created[i] = 1;
    else
      run_worker();
#endif
  }

  for (int i = 0; i < nthreads; i++) {
    if (!created[i])
      continue;
#if defined(_WIN32)
    WaitForSingleObject(threads[i], INFINITE);
    CloseHandle(threads[i]);
#else
    pthread_join(threads[i], NULL);
#endif
  }

  uint64_t best = atomic_load(&g_best);

  free(threads);
  free(created);

  if (best != UINT64_MAX) {
    printf("{\"answer\":%llu}\n", (unsigned long long)best);
    return 0;
  }
  puts("{\"error\":\"answer not found in range\"}");
  return 1;
}