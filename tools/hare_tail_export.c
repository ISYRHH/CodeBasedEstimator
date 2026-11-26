/* Export public tail-generator columns from the supplied reference encoder.
 * Message bit j is bit (j % 8) of byte (j / 8). Output bit i is coordinate
 * PARAM_L2+i, packed into bit i of a uint64_t. No randomness is sampled.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "code.h"
#include "drng.h"
#include "parameters.h"

/* Required by the linked API_PKC wrappers; unused by code_encode. */
DRNG_ctx drng_algorithm;

static uint64_t tail_of(const uint64_t *encoded) {
    uint64_t tail = 0;
    for (unsigned i = 0; i < PARAM_NV2; ++i) {
        const unsigned position = PARAM_L2 + i;
        tail |= ((encoded[position >> 6] >> (position & 63u)) & 1u) << i;
    }
    return tail;
}

int main(void) {
    uint64_t columns[8 * PARAM_K];
    uint8_t message[PARAM_K] = {0};
    uint64_t encoded[VEC_N_SIZE_64] = {0};

    if (PARAM_NV2 <= 0 || PARAM_NV2 >= 64 || PARAM_L2 < 0 ||
            PARAM_L2 + PARAM_NV2 != PARAM_L1 || PARAM_L1 > PARAM_N ||
            PARAM_K <= 0 || 8 * PARAM_K != 8 * PARAM_SECURITY_BYTES) {
        fprintf(stderr, "Unsupported reference tail parameters\n");
        return 1;
    }

    code_encode(encoded, message);
    if (tail_of(encoded) != 0) {
        fprintf(stderr, "The reference encoder does not map zero to zero\n");
        return 2;
    }
    for (unsigned j = 0; j < 8 * PARAM_K; ++j) {
        memset(message, 0, sizeof(message));
        memset(encoded, 0, sizeof(encoded));
        message[j >> 3] = (uint8_t)(1u << (j & 7u));
        code_encode(encoded, message);
        columns[j] = tail_of(encoded);
    }

    /* Check the column interpretation on deterministic combinations as well
     * as unit inputs. This is a regression check, not a linearity proof. */
    for (unsigned round = 0; round < 16; ++round) {
        uint64_t expected = 0;
        for (unsigned j = 0; j < PARAM_K; ++j) {
            message[j] = (uint8_t)(17u * j + 29u * round + 3u);
        }
        for (unsigned j = 0; j < 8 * PARAM_K; ++j) {
            if ((message[j >> 3] >> (j & 7u)) & 1u) expected ^= columns[j];
        }
        memset(encoded, 0, sizeof(encoded));
        code_encode(encoded, message);
        if (tail_of(encoded) != expected) {
            fprintf(stderr, "Tail column-combination check failed\n");
            return 3;
        }
    }

    printf("{\"ring_length\":%d,\"message_bits\":%d,\"tail_start\":%d,"
           "\"tail_bits\":%d,\"encoded_bits\":%d,\"wr\":%d,\"we\":%d,"
           "\"message_columns\":[",
           PARAM_N, 8 * PARAM_K, PARAM_L2, PARAM_NV2, PARAM_L1,
           PARAM_OMEGA_R, PARAM_OMEGA_E);
    for (unsigned j = 0; j < 8 * PARAM_K; ++j) {
        printf("%s%" PRIu64, j ? "," : "", columns[j]);
    }
    printf("]}\n");
    return 0;
}
