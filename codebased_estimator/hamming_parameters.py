"""Reviewed parameter snapshot from local/HammingSchemes (2026-10-03).

References identify the submitted implementation/specification and the source
of weight conventions. These are input parameters, not claimed security bits.
Legacy/specification-only sets are explicitly noted; compile-time overrides
and obsolete QUBE optimized-only variants are not included.
"""

HAMMING_PARAMETERS = [{'scheme': 'BIKE_MLThre',
  'parameter_set': 'BIKE_MLThre-128',
  'parameters': {'r': 12323, 'w': 142, 't': 134, 'dv': 71},
  'references': ['local/HammingSchemes/BIKE_MLThre/Implementations/reference/defs.h:176-182',
                 'local/HammingSchemes/BIKE_MLThre/Implementations/reference/kem.c:127-128'],
  'notes': ['w = 2 * DV: the two secret blocks h0 and h1 each have weight DV.']},
 {'scheme': 'BIKE_MLThre',
  'parameter_set': 'BIKE_MLThre-192',
  'parameters': {'r': 24659, 'w': 206, 't': 199, 'dv': 103},
  'references': ['local/HammingSchemes/BIKE_MLThre/Implementations/reference/defs.h:161-167',
                 'local/HammingSchemes/BIKE_MLThre/Implementations/reference/kem.c:127-128'],
  'notes': ['w = 2 * DV: the two secret blocks h0 and h1 each have weight DV.',
            'Legacy compatibility parameter set in the reference implementation; not a standard submitted 128/256/512 '
            'set.']},
 {'scheme': 'BIKE_MLThre',
  'parameter_set': 'BIKE_MLThre-256',
  'parameters': {'r': 40973, 'w': 274, 't': 264, 'dv': 137},
  'references': ['local/HammingSchemes/BIKE_MLThre/Implementations/reference/defs.h:146-152',
                 'local/HammingSchemes/BIKE_MLThre/Implementations/reference/kem.c:127-128'],
  'notes': ['w = 2 * DV: the two secret blocks h0 and h1 each have weight DV.']},
 {'scheme': 'BIKE_MLThre',
  'parameter_set': 'BIKE_MLThre-512',
  'parameters': {'r': 150001, 'w': 546, 't': 524, 'dv': 273},
  'references': ['local/HammingSchemes/BIKE_MLThre/Implementations/reference/defs.h:80-100',
                 'local/HammingSchemes/BIKE_MLThre/Implementations/reference/kem.c:127-128'],
  'notes': ['w = 2 * DV: the two secret blocks h0 and h1 each have weight DV.',
            'Source labels the 512-bit-classical defaults as candidate parameters; custom compile-time parameter '
            'overrides are not evaluated.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-1',
  'parameters': {'r': 10301, 'w': 81, 't': 201, 'd': 27},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.',
            'Specification-only NIST variant; the local submission implements only TRIKE-2/5/7/9.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-2',
  'parameters': {'r': 15581, 'w': 105, 't': 263, 'd': 35},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-2/src/trike_params.h:8-12',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-2/src/sample.c:186-188'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.',
            'Use r = 15581 from Table 1 and reference code; the DFR Table 8 contains an inconsistent r = 15541.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-3',
  'parameters': {'r': 22003, 'w': 123, 't': 319, 'd': 41},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.',
            'Specification-only NIST variant; the local submission implements only TRIKE-2/5/7/9.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-5',
  'parameters': {'r': 35363, 'w': 165, 't': 429, 'd': 55},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-5/src/trike_params.h:8-12',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-5/src/sample.c:186-188'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-7',
  'parameters': {'r': 69691, 'w': 249, 't': 659, 'd': 83},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-7/src/trike_params.h:8-12',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-7/src/sample.c:186-188'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.']},
 {'scheme': 'TRIKE',
  'parameter_set': 'TRIKE-9',
  'parameters': {'r': 114043, 'w': 333, 't': 877, 'd': 111},
  'references': ['local/HammingSchemes/TRIKE/Algorithm specifications/TRIKE算法文档.pdf:page 10, Table 1',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-9/src/trike_params.h:8-12',
                 'local/HammingSchemes/TRIKE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/TRIKE-9/src/sample.c:186-188'],
  'notes': ['w = 3 * PARAM_D: h0, h1, h2 each have weight PARAM_D.']},
 {'scheme': 'HARE',
  'parameter_set': 'HARE-128',
  'parameters': {'r': 20899, 'w': 79, 'wr': 79},
  'references': ['local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HARE-128/kr/parameters.h:15-18',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:48-49',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:115-117'],
  'notes': ['r = PARAM_N, w = PARAM_OMEGA, wr = PARAM_OMEGA_R; key and message ISD weights are both twice their '
            'per-block weight.']},
 {'scheme': 'HARE',
  'parameter_set': 'HARE-256',
  'parameters': {'r': 52379, 'w': 131, 'wr': 131},
  'references': ['local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HARE-256/kr/parameters.h:15-18',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:48-49',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:115-117'],
  'notes': ['r = PARAM_N, w = PARAM_OMEGA, wr = PARAM_OMEGA_R; key and message ISD weights are both twice their '
            'per-block weight.']},
 {'scheme': 'HARE',
  'parameter_set': 'HARE-384',
  'parameters': {'r': 104869, 'w': 193, 'wr': 193},
  'references': ['local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HARE-384/kr/parameters.h:15-18',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:48-49',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:115-117'],
  'notes': ['r = PARAM_N, w = PARAM_OMEGA, wr = PARAM_OMEGA_R; key and message ISD weights are both twice their '
            'per-block weight.']},
 {'scheme': 'HARE',
  'parameter_set': 'HARE-512',
  'parameters': {'r': 173981, 'w': 259, 'wr': 259},
  'references': ['local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HARE-512/kr/parameters.h:15-18',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:48-49',
                 'local/HammingSchemes/HARE/Implementations and '
                 'Test_Vectors/Implementations/_shared/hare_core/ref/hqc.c:115-117'],
  'notes': ['r = PARAM_N, w = PARAM_OMEGA, wr = PARAM_OMEGA_R; key and message ISD weights are both twice their '
            'per-block weight.']},
 {'scheme': 'NSS-HQC',
  'parameter_set': 'NSS-HQC-128',
  'parameters': {'r': 29443, 'wsk': 73, 'wr1': 66, 'wr2': 66},
  'references': ['local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/params.h:7-11',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:819-820',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:721-723'],
  'notes': ['Local implementation directory is HQC-128; catalogue uses NSS-HQC-128 to identify the scheme '
            'unambiguously.',
            'r = NSS_HQC_N; key weight = 2 * NSS_HQC_W_SK; message weight = NSS_HQC_W_R1 + NSS_HQC_W_R2.']},
 {'scheme': 'NSS-HQC',
  'parameter_set': 'NSS-HQC-256',
  'parameters': {'r': 54493, 'wsk': 117, 'wr1': 106, 'wr2': 106},
  'references': ['local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-256/params.h:7-11',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:819-820',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:721-723'],
  'notes': ['Local implementation directory is HQC-256; catalogue uses NSS-HQC-256 to identify the scheme '
            'unambiguously.',
            'r = NSS_HQC_N; key weight = 2 * NSS_HQC_W_SK; message weight = NSS_HQC_W_R1 + NSS_HQC_W_R2.']},
 {'scheme': 'NSS-HQC',
  'parameter_set': 'NSS-HQC-384',
  'parameters': {'r': 122579, 'wsk': 175, 'wr1': 159, 'wr2': 159},
  'references': ['local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-384/params.h:7-11',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:819-820',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:721-723'],
  'notes': ['Local implementation directory is HQC-384; catalogue uses NSS-HQC-384 to identify the scheme '
            'unambiguously.',
            'r = NSS_HQC_N; key weight = 2 * NSS_HQC_W_SK; message weight = NSS_HQC_W_R1 + NSS_HQC_W_R2.']},
 {'scheme': 'NSS-HQC',
  'parameter_set': 'NSS-HQC-512',
  'parameters': {'r': 217901, 'wsk': 233, 'wr1': 213, 'wr2': 213},
  'references': ['local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-512/params.h:7-11',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:819-820',
                 'local/HammingSchemes/NSS-HQC/Implementations and '
                 'Test_Vectors/Implementations/Reference_Implementation/HQC-128/nss_hqc_core.c:721-723'],
  'notes': ['Local implementation directory is HQC-512; catalogue uses NSS-HQC-512 to identify the scheme '
            'unambiguously.',
            'r = NSS_HQC_N; key weight = 2 * NSS_HQC_W_SK; message weight = NSS_HQC_W_R1 + NSS_HQC_W_R2.']},
 {'scheme': 'TriQ-KEM',
  'parameter_set': 'TriQ-KEM-128',
  'parameters': {'r': 16301, 'wx': 67, 'wy': 67, 'wr': 67},
  'references': ['local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq-128/parameters.h:14-20',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:47-48',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:113-115'],
  'notes': ['r = PARAM_N; wx = wy = PARAM_OMEGA; wr = PARAM_OMEGA_R.',
            'Message sampling uses a block-distributed fixed-weight sampler; this preliminary mapping retains only '
            'total Hamming weight, per HammingISD.md.']},
 {'scheme': 'TriQ-KEM',
  'parameter_set': 'TriQ-KEM-256',
  'parameters': {'r': 50363, 'wx': 132, 'wy': 132, 'wr': 132},
  'references': ['local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-256/src/ref/triq-256/parameters.h:14-20',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:47-48',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:113-115'],
  'notes': ['r = PARAM_N; wx = wy = PARAM_OMEGA; wr = PARAM_OMEGA_R.',
            'Message sampling uses a block-distributed fixed-weight sampler; this preliminary mapping retains only '
            'total Hamming weight, per HammingISD.md.']},
 {'scheme': 'TriQ-KEM',
  'parameter_set': 'TriQ-KEM-384',
  'parameters': {'r': 97651, 'wx': 196, 'wy': 196, 'wr': 196},
  'references': ['local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-384/src/ref/triq-384/parameters.h:14-20',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:47-48',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:113-115'],
  'notes': ['r = PARAM_N; wx = wy = PARAM_OMEGA; wr = PARAM_OMEGA_R.',
            'Message sampling uses a block-distributed fixed-weight sampler; this preliminary mapping retains only '
            'total Hamming weight, per HammingISD.md.']},
 {'scheme': 'TriQ-KEM',
  'parameter_set': 'TriQ-KEM-512',
  'parameters': {'r': 157627, 'wx': 260, 'wy': 260, 'wr': 260},
  'references': ['local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-512/src/ref/triq-512/parameters.h:14-20',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:47-48',
                 'local/HammingSchemes/TriQ-KEM/Implementations/Reference_Implementation/TriQ-KEM-128/src/ref/triq_pke.c:113-115'],
  'notes': ['r = PARAM_N; wx = wy = PARAM_OMEGA; wr = PARAM_OMEGA_R.',
            'Message sampling uses a block-distributed fixed-weight sampler; this preliminary mapping retains only '
            'total Hamming weight, per HammingISD.md.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-128',
  'parameters': {'r': 15373, 'd': 2, 'wx': [44, 41], 'wy': [47, 40], 'wr': [42, 45], 'wt': [44, 45]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-128/parameters.h:15-22',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-128/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-128/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-256',
  'parameters': {'r': 33827, 'd': 2, 'wx': [65, 63], 'wy': [72, 69], 'wr': [63, 66], 'wt': [71, 74]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-256/parameters.h:31-36',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-256/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-256/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-512',
  'parameters': {'r': 106261, 'd': 2, 'wx': [127, 126], 'wy': [143, 131], 'wr': [123, 134], 'wt': [137, 138]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-512/parameters.h:47-52',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-512/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-512/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-E-128',
  'parameters': {'r': 14621, 'd': 2, 'wx': [44, 41], 'wy': [47, 40], 'wr': [42, 45], 'wt': [44, 45]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-128/parameters.h:69-76',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-128/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-128/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-E-256',
  'parameters': {'r': 32261, 'd': 2, 'wx': [69, 64], 'wy': [72, 64], 'wr': [63, 73], 'wt': [66, 72]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-256/parameters.h:84-89',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-256/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-256/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-1-E-512',
  'parameters': {'r': 102437, 'd': 2, 'wx': [128, 123], 'wy': [140, 136], 'wr': [126, 129], 'wt': [136, 141]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-512/parameters.h:100-105',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-512/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-1-E-512/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-2-E-128',
  'parameters': {'r': 10253,
                 'd': 4,
                 'wx': [25, 25, 22, 21],
                 'wy': [25, 25, 22, 21],
                 'wr': [22, 23, 25, 25],
                 'wt': [22, 23, 25, 25]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-128/parameters.h:122-129',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-128/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-128/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance. PARAM_OMEGA and PARAM_OMEGA_R each contain four weights and are reused for both vectors, so '
            'total ISD weight is twice the corresponding array sum.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-2-E-256',
  'parameters': {'r': 21523,
                 'd': 4,
                 'wx': [38, 38, 33, 33],
                 'wy': [38, 38, 33, 33],
                 'wr': [34, 34, 38, 38],
                 'wt': [34, 34, 38, 38]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-256/parameters.h:137-142',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-256/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-256/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance. PARAM_OMEGA and PARAM_OMEGA_R each contain four weights and are reused for both vectors, so '
            'total ISD weight is twice the corresponding array sum.']},
 {'scheme': 'Mito',
  'parameter_set': 'Mito-2-E-512',
  'parameters': {'r': 65293,
                 'd': 4,
                 'wx': [72, 72, 66, 62],
                 'wy': [72, 72, 66, 62],
                 'wr': [65, 66, 70, 73],
                 'wt': [65, 66, 70, 73]},
  'references': ['local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-512/parameters.h:153-158',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-512/mito_pke.c:41-42',
                 'local/HammingSchemes/Mito/Implementations/Reference_Implementation/Mito-2-E-512/mito_pke.c:93-94'],
  'notes': ['r = PARAM_N; d = PARAM_L (number of ring coordinates); PARAM_OMEGA_E is not part of the requested message '
            'ISD instance. PARAM_OMEGA and PARAM_OMEGA_R each contain four weights and are reused for both vectors, so '
            'total ISD weight is twice the corresponding array sum.']},
 {'scheme': 'QUBE',
  'parameter_set': 'QUBE-128',
  'parameters': {'r': 13109, 'wx': 74, 'wy': 76, 'wf': 29, 'wg': 27},
  'references': ['local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-128/src/ref/parameters.h:14-23',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-128/src/ref/qube.c:64-69',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-128/src/ref/qube.c:128-136'],
  'notes': ['Use the five PDF-aligned reference parameter sets. r = PARAM_N, wf = PARAM_OMEGA_R21 = PARAM_OMEGA_R22, '
            'wg = PARAM_OMEGA_R11; PARAM_OMEGA_E is excluded by the requested ISD mapping.']},
 {'scheme': 'QUBE',
  'parameter_set': 'QUBE-192',
  'parameters': {'r': 25357, 'wx': 110, 'wy': 113, 'wf': 43, 'wg': 39},
  'references': ['local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-192/src/ref/parameters.h:14-23',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-192/src/ref/qube.c:64-69',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-192/src/ref/qube.c:128-136'],
  'notes': ['Use the five PDF-aligned reference parameter sets. r = PARAM_N, wf = PARAM_OMEGA_R21 = PARAM_OMEGA_R22, '
            'wg = PARAM_OMEGA_R11; PARAM_OMEGA_E is excluded by the requested ISD mapping.']},
 {'scheme': 'QUBE',
  'parameter_set': 'QUBE-256',
  'parameters': {'r': 41651, 'wx': 146, 'wy': 151, 'wf': 57, 'wg': 52},
  'references': ['local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-256/src/ref/parameters.h:14-23',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-256/src/ref/qube.c:64-69',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-256/src/ref/qube.c:128-136'],
  'notes': ['Use the five PDF-aligned reference parameter sets. r = PARAM_N, wf = PARAM_OMEGA_R21 = PARAM_OMEGA_R22, '
            'wg = PARAM_OMEGA_R11; PARAM_OMEGA_E is excluded by the requested ISD mapping.']},
 {'scheme': 'QUBE',
  'parameter_set': 'QUBE-384',
  'parameters': {'r': 82757, 'wx': 219, 'wy': 226, 'wf': 85, 'wg': 78},
  'references': ['local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-384/src/ref/parameters.h:14-23',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-384/src/ref/qube.c:64-69',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-384/src/ref/qube.c:128-136'],
  'notes': ['Use the five PDF-aligned reference parameter sets. r = PARAM_N, wf = PARAM_OMEGA_R21 = PARAM_OMEGA_R22, '
            'wg = PARAM_OMEGA_R11; PARAM_OMEGA_E is excluded by the requested ISD mapping.']},
 {'scheme': 'QUBE',
  'parameter_set': 'QUBE-512',
  'parameters': {'r': 135851, 'wx': 291, 'wy': 301, 'wf': 113, 'wg': 103},
  'references': ['local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-512/src/ref/parameters.h:14-23',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-512/src/ref/qube.c:64-69',
                 'local/HammingSchemes/QUBE/Implementations/Reference_Implementation/qube-512/src/ref/qube.c:128-136'],
  'notes': ['Use the five PDF-aligned reference parameter sets. r = PARAM_N, wf = PARAM_OMEGA_R21 = PARAM_OMEGA_R22, '
            'wg = PARAM_OMEGA_R11; PARAM_OMEGA_E is excluded by the requested ISD mapping.']},
 {'scheme': 'QCTM',
  'parameter_set': 'QCTM128',
  'parameters': {'n': 10070, 'm': 18, 't': 285},
  'references': ['local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM128/scheme_api.h:4-9',
                 'local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM128/sizes.h:15-24'],
  'notes': ['t is the Goppa degree, not ERROR_WEIGHT; binary ISD w = (t - 1) / 2 and k = n - m * (t - 1) - 1. Key '
            'recovery is unsupported: HammingISD.md provides no generic ISD instance and only discusses resistance to '
            'structural attacks.']},
 {'scheme': 'QCTM',
  'parameter_set': 'QCTM256',
  'parameters': {'n': 19000, 'm': 18, 't': 513},
  'references': ['local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM256/scheme_api.h:4-9',
                 'local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM256/sizes.h:15-24'],
  'notes': ['t is the Goppa degree, not ERROR_WEIGHT; binary ISD w = (t - 1) / 2 and k = n - m * (t - 1) - 1. Key '
            'recovery is unsupported: HammingISD.md provides no generic ISD instance and only discusses resistance to '
            'structural attacks.']},
 {'scheme': 'QCTM',
  'parameter_set': 'QCTM512',
  'parameters': {'n': 38000, 'm': 18, 't': 1007},
  'references': ['local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM512/scheme_api.h:4-9',
                 'local/HammingSchemes/QCTM/Implementations/Reference_Implementation/QCTM512/sizes.h:15-24'],
  'notes': ['t is the Goppa degree, not ERROR_WEIGHT; binary ISD w = (t - 1) / 2 and k = n - m * (t - 1) - 1. Key '
            'recovery is unsupported: HammingISD.md provides no generic ISD instance and only discusses resistance to '
            'structural attacks.']},
 {'scheme': 'UVW-KEM',
  'parameter_set': 'UVW-KEM-128',
  'parameters': {'n': 860, 'k1': 215, 'k2': 215, 'w': 116, 'q': 433},
  'references': ['local/HammingSchemes/UVW-KEM/Implementations/Reference_Implementation/UVW-KEM-128/include/params.h:8-14'],
  'notes': ['Nonbinary Syndrome Decoding over Fq: k = k1 + k2. Key recovery is unsupported: the note calls for a '
            'structured-codeword distinguisher across multiple weights rather than one fixed generic ISD instance.']},
 {'scheme': 'UVW-KEM',
  'parameter_set': 'UVW-KEM-256',
  'parameters': {'n': 1708, 'k1': 427, 'k2': 427, 'w': 232, 'q': 857},
  'references': ['local/HammingSchemes/UVW-KEM/Implementations/Reference_Implementation/UVW-KEM-256/include/params.h:8-14'],
  'notes': ['Nonbinary Syndrome Decoding over Fq: k = k1 + k2. Key recovery is unsupported: the note calls for a '
            'structured-codeword distinguisher across multiple weights rather than one fixed generic ISD instance.']},
 {'scheme': 'UVW-KEM',
  'parameter_set': 'UVW-KEM-512',
  'parameters': {'n': 3412, 'k1': 853, 'k2': 853, 'w': 463, 'q': 1709},
  'references': ['local/HammingSchemes/UVW-KEM/Implementations/Reference_Implementation/UVW-KEM-512/include/params.h:8-14'],
  'notes': ['Nonbinary Syndrome Decoding over Fq: k = k1 + k2. Key recovery is unsupported: the note calls for a '
            'structured-codeword distinguisher across multiple weights rather than one fixed generic ISD instance.']}]
