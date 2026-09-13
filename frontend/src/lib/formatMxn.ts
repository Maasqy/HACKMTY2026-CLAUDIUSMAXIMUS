// Formato canonico de peso mexicano. Se usa en todas las vistas para que un
// juez no vea inconsistencias entre "$1,234.56" y "$1234.56 MXN".

const MXN_FORMATTER = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "MXN",
  minimumFractionDigits: 2,
});

export function formatMxn(x: number): string {
  return MXN_FORMATTER.format(x);
}
