# Base de Datos — Sistema de Investigación de CFDI

Base de datos que concentra la información necesaria para representar operaciones comerciales, fiscales, contables y bancarias dentro de un escenario de investigación de CFDI.

La arquitectura está centrada en **`vendors`**, desde donde se conectan facturas, órdenes de compra, contratos, movimientos bancarios y la referencia `efos_list`.

---

## 1. Arquitectura general

La estructura puede resumirse de la siguiente manera:

```text
                              ┌───────────────┐
                              │    VENDORS    │
                              │  Proveedores  │
                              └───────┬───────┘
                                      │
               ┌──────────────────────┼──────────────────────┐
               │                      │                      │
               ▼                      ▼                      ▼
        ┌─────────────┐       ┌────────────────┐      ┌─────────────┐
        │  INVOICES   │       │ PURCHASE_      │      │  CONTRACTS  │
        │    CFDI     │       │   ORDERS       │      │             │
        └──────┬──────┘       └────────────────┘      └─────────────┘
               │
               ▼
        ┌─────────────┐
        │   LEDGER    │
        │ Contabilidad│
        └─────────────┘


        ┌─────────────┐
        │  BANK_TXNS  │
        │ Movimientos │
        │  bancarios  │
        └──────┬──────┘
               ▲
          ┌────┴────┐
          │         │
       VENDORS   EMPLOYEES
       (CLABE)    (CLABE)


        VENDORS
           │
          RFC
           ▼
     ┌─────────────┐
     │  EFOS_LIST  │
     │  Referencia │
     │    69-B     │
     └─────────────┘
```

Las principales entidades son:

- **`vendors`**: entidad central de proveedores.
- **`invoices`**: CFDI emitidos.
- **`purchase_orders`**: órdenes de compra.
- **`contracts`**: contratos con proveedores.
- **`ledger`**: registros contables asociados a facturas.
- **`bank_txns`**: movimientos bancarios.
- **`employees`**: empleados relacionados mediante información bancaria.
- **`efos_list`**: referencia de contribuyentes bajo el procedimiento 69-B.

---

## 2. Tablas

### `vendors`

Entidad central que representa a los proveedores.

| Campo | Descripción |
|---|---|
| `rfc` | RFC único del proveedor. **PK** |
| `legal_name` | Razón social o nombre legal. |
| `registered_date` | Fecha de registro. |
| `address` | Dirección registrada. |
| `bank_clabe` | CLABE bancaria asociada. |
| `category` | Categoría o actividad del proveedor. |
| `contact_email` | Correo de contacto. |

---

### `invoices`

Contiene los CFDI emitidos.

| Campo | Descripción |
|---|---|
| `uuid` | Identificador único del CFDI. **PK** |
| `issuer_rfc` | RFC del emisor. **FK lógica → `vendors.rfc`** |
| `receiver_rfc` | RFC del receptor. |
| `issue_date` | Fecha de emisión. |
| `subtotal` | Importe antes de impuestos. |
| `iva` | IVA. |
| `total` | Importe total. |
| `concepto_text` | Descripción del concepto facturado. |
| `uso_cfdi` | Uso fiscal del CFDI. |
| `forma_pago` | Forma de pago. |
| `metodo_pago` | Método de pago. |
| `status` | Estado de la factura. |

---

### `ledger`

Representa los registros contables asociados a las operaciones.

| Campo | Descripción |
|---|---|
| `entry_id` | Identificador del registro. **PK** |
| `date` | Fecha del registro. |
| `account_code` | Código de cuenta contable. |
| `account_name` | Nombre de la cuenta. |
| `debit` | Débito. |
| `credit` | Crédito. |
| `description` | Descripción del movimiento. |
| `invoice_uuid` | UUID de la factura relacionada. **FK lógica → `invoices.uuid`** |
| `cost_center` | Centro de costos. |
| `approver` | Aprobador del movimiento. |

---

### `bank_txns`

Contiene los movimientos bancarios.

| Campo | Descripción |
|---|---|
| `txn_id` | Identificador de la transacción. **PK** |
| `date` | Fecha del movimiento. |
| `from_clabe` | CLABE de origen. |
| `to_clabe` | CLABE de destino. |
| `amount` | Monto transferido. |
| `reference` | Referencia del movimiento. |
| `channel` | Canal utilizado. |

Las relaciones con proveedores y empleados se realizan mediante sus respectivas CLABE.

---

### `purchase_orders`

Representa las órdenes de compra.

| Campo | Descripción |
|---|---|
| `po_id` | Identificador de la orden. **PK** |
| `vendor_rfc` | RFC del proveedor. **FK lógica → `vendors.rfc`** |
| `date` | Fecha de la orden. |
| `amount` | Monto autorizado. |
| `requester` | Solicitante. |
| `approver` | Aprobador. |
| `description` | Descripción de la compra. |

---

### `contracts`

Representa los contratos establecidos con proveedores.

| Campo | Descripción |
|---|---|
| `contract_id` | Identificador del contrato. **PK** |
| `vendor_rfc` | RFC del proveedor. **FK lógica → `vendors.rfc`** |
| `start_date` | Fecha de inicio. |
| `value` | Valor del contrato. |
| `scope_text` | Alcance o descripción del contrato. |

---

### `employees`

Representa a los empleados internos.

| Campo | Descripción |
|---|---|
| `emp_id` | Identificador del empleado. **PK** |
| `name` | Nombre. |
| `role` | Puesto o función. |
| `bank_clabe` | CLABE asociada. |
| `hire_date` | Fecha de contratación. |

La conexión con `bank_txns` se realiza mediante `bank_clabe`.

---

### `efos_list`

Tabla de referencia de contribuyentes publicados bajo el procedimiento 69-B.

| Campo | Descripción |
|---|---|
| `rfc` | RFC del contribuyente. **PK** |
| `legal_name` | Razón social. |
| `status` | Estatus (`presunto` o `definitivo`). |
| `publication_date` | Fecha de publicación. |

---

## 3. Relaciones principales

| Origen | Destino | Cardinalidad | Relación |
|---|---|---:|---|
| `vendors.rfc` | `invoices.issuer_rfc` | 1:N | Un proveedor puede emitir múltiples facturas. |
| `vendors.rfc` | `purchase_orders.vendor_rfc` | 1:N | Un proveedor puede tener múltiples órdenes de compra. |
| `vendors.rfc` | `contracts.vendor_rfc` | 1:N | Un proveedor puede tener múltiples contratos. |
| `invoices.uuid` | `ledger.invoice_uuid` | 1:N | Una factura puede tener múltiples registros contables. |
| `vendors.bank_clabe` | `bank_txns.from_clabe / to_clabe` | Indirecta | Conecta movimientos bancarios con proveedores. |
| `employees.bank_clabe` | `bank_txns.from_clabe / to_clabe` | Indirecta | Conecta movimientos bancarios con empleados. |
| `vendors.rfc` | `efos_list.rfc` | Comparación | Permite contrastar un proveedor contra la lista 69-B. |

### Relaciones físicas vs. lógicas

No todas las relaciones están implementadas como **foreign keys físicas** dentro de SQLite.

Las relaciones principales son:

```text
vendors.rfc
    ├── invoices.issuer_rfc
    ├── purchase_orders.vendor_rfc
    └── contracts.vendor_rfc

invoices.uuid
    └── ledger.invoice_uuid

vendors.bank_clabe
    └── bank_txns.from_clabe / to_clabe

employees.bank_clabe
    └── bank_txns.from_clabe / to_clabe

vendors.rfc
    └── efos_list.rfc
```

En particular, `bank_txns` no contiene un `vendor_rfc`, `emp_id` o `invoice_uuid`. La asociación con proveedores y empleados se obtiene mediante las CLABE almacenadas en dichas entidades.

De igual forma, la relación entre `vendors` y `efos_list` se establece mediante la coincidencia de `rfc`, no necesariamente mediante una foreign key física.

---

## 4. Modelo relacional simplificado

```text
                           VENDORS
                        PK: rfc
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          │ 1:N            │ 1:N            │ 1:N
          ▼                ▼                ▼
      INVOICES      PURCHASE_ORDERS      CONTRACTS
      PK: uuid        PK: po_id        PK: contract_id
          │
          │ 1:N
          ▼
       LEDGER
    PK: entry_id


     VENDORS ──────┐
       CLABE        │
                    ├──── BANK_TXNS
     EMPLOYEES ─────┘
       CLABE


     VENDORS
       │
       │ RFC
       ▼
    EFOS_LIST
```

## 5. Resumen

La base se estructura alrededor de **`vendors`** y separa la información en diferentes fuentes operativas:

```text
Proveedor
   │
   ├── Contratos
   ├── Órdenes de compra
   ├── Facturas
   │      └── Registros contables
   │
   ├── Cuenta bancaria
   │      └── Movimientos bancarios
   │
   └── RFC
          └── EFOS / 69-B

Empleados
   └── Cuenta bancaria
          └── Movimientos bancarios
```

La estructura permite mantener separadas las distintas fuentes de información y conectarlas mediante sus identificadores principales: **RFC, UUID y CLABE**.