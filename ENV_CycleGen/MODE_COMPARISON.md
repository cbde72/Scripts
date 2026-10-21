# Operating Mode comparison

Reference configured by schema 4: `2.ENV_Test_Plan_Cp_r00v05(2).docx`.

The referenced Word document is not present in this repository, so a direct
line-by-line comparison cannot currently be performed. No operating mode was
changed during the schema-4 migration.

Voltage mapping implemented from `global.voltage`:

- Mode `1.x`: `off_voltage_v`
- Mode `2.x`: `ub_voltage_v`
- Mode `3.x`: `ua_voltage_v`
- ENV_004 function checks: explicit `nominal_voltage_v`,
  `minimum_voltage_v`, or `maximum_voltage_v`
- ENV_015 Umin/Umax function checks: explicit `minimum_voltage_v` or
  `maximum_voltage_v`

The existing test generators remain the source of the phase-specific operating
modes. Any discrepancy found when the Word source becomes available must be
resolved explicitly rather than silently changing the generated profiles.
