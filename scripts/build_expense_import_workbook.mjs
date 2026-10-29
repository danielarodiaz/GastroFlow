import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const [jsonPath, outputPath] = process.argv.slice(2);
if (!jsonPath || !outputPath) {
  throw new Error("Uso: node build_expense_import_workbook.mjs <datos.json> <salida.xlsx>");
}

const report = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Resumen");
const ticketSheet = workbook.worksheets.add("Tickets");
const detailSheet = workbook.worksheets.add("Detalle importacion");
const fontFamily = "Arial";
const darkGreen = "#285943";
const mediumGreen = "#4E8066";
const lightGreen = "#E6F0EA";
const lightGray = "#F3F4F6";
const amber = "#FEF3C7";
const amberText = "#92400E";


function asDate(value) {
  return new Date(`${value}T00:00:00Z`);
}


function styleHeader(range, fill = darkGreen) {
  range.format = {
    fill,
    font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "inside", style: "thin", color: "#FFFFFF" },
  };
}


function styleBody(range) {
  range.format.font = { name: fontFamily, size: 10, color: "#1F2937" };
  range.format.verticalAlignment = "center";
}


summarySheet.showGridLines = false;
summarySheet.tabColor = darkGreen;
summarySheet.getRange("A2").values = [["Preparación de gastos históricos"]];
summarySheet.getRange("A2:F2").format.font = { name: fontFamily, size: 15, bold: true, color: darkGreen };
summarySheet.getRange("A4:B4").values = [["Control", "Resultado"]];
styleHeader(summarySheet.getRange("A4:B4"));
const summary = report.summary;
summarySheet.getRange("A5:B14").values = [
  ["Archivo fuente", summary.source_file],
  ["SHA-256", summary.source_sha256],
  ["Filas de ítems", Number(summary.source_rows)],
  ["Tickets agrupados", Number(summary.ticket_groups)],
  ["Ítems listos", Number(summary.ready_items)],
  ["Ítems para revisar", Number(summary.review_items)],
  ["Ítems sin marca", Number(summary.items_without_brand)],
  ["Primera fecha", asDate(summary.first_date)],
  ["Última fecha", asDate(summary.last_date)],
  ["Total conciliado", Number(summary.prepared_total)],
];
styleBody(summarySheet.getRange("A5:B14"));
summarySheet.getRange("B12:B13").setNumberFormat("dd/mm/yyyy");
summarySheet.getRange("B14").setNumberFormat('"$"#,##0.00');
summarySheet.getRange("A5:A14").format.fill = lightGreen;
summarySheet.getRange("A5:A14").format.font = { name: fontFamily, size: 10, bold: true, color: "#1F3D2F" };
summarySheet.getRange("A16:F16").values = [[
  "Fila Excel", "Motivo", "Cantidad original", "Cantidad propuesta", "Unidad", "Observacion"
]];
styleHeader(summarySheet.getRange("A16:F16"), mediumGreen);
const reviewRows = report.rows.filter((row) => row.status === "REVISAR");
if (reviewRows.length > 0) {
  summarySheet.getRangeByIndexes(16, 0, reviewRows.length, 6).values = reviewRows.map((row) => [
    Number(row.excel_row),
    row.motive_normalized,
    row.quantity_original ?? "",
    Number(row.quantity),
    row.unit,
    row.note ?? "",
  ]);
  styleBody(summarySheet.getRangeByIndexes(16, 0, reviewRows.length, 6));
  summarySheet.getRangeByIndexes(16, 0, reviewRows.length, 6).format.fill = amber;
  summarySheet.getRangeByIndexes(16, 0, reviewRows.length, 6).format.font = {
    name: fontFamily, size: 10, color: amberText,
  };
  summarySheet.getRangeByIndexes(16, 3, reviewRows.length, 1).setNumberFormat("0.000");
} else {
  summarySheet.getRange("A17:F17").format.fill = lightGreen;
  summarySheet.getRange("A17:F17").format.font = {
    name: fontFamily, size: 10, bold: true, color: darkGreen,
  };
  summarySheet.getRange("A17").values = [["No hay ítems pendientes de revisión."]];
}
summarySheet.getRange("A25:F25").merge();
summarySheet.getRange("A25").values = [[
  reviewRows.length > 0
    ? "La importación a la base debe permanecer bloqueada mientras existan ítems para revisión."
    : `Las ${summary.ready_items} filas están normalizadas y conciliadas. La planilla está lista para el ensayo de importación.`
]];
summarySheet.getRange("A25").format = {
  fill: reviewRows.length > 0 ? amber : lightGreen,
  font: {
    name: fontFamily,
    size: 10,
    bold: true,
    color: reviewRows.length > 0 ? amberText : darkGreen,
  },
  wrapText: true,
};
summarySheet.getRange("A1:H27").format.verticalAlignment = "center";
summarySheet.getRange("A:A").format.columnWidth = 24;
summarySheet.getRange("B:B").format.columnWidth = 66;
summarySheet.getRange("C:C").format.columnWidth = 22;
summarySheet.getRange("D:E").format.columnWidth = 18;
summarySheet.getRange("F:F").format.columnWidth = 55;
summarySheet.getRange("A2:H2").format.rowHeight = 26;
summarySheet.getRange("16:16").format.rowHeight = 24;
summarySheet.getRange("25:25").format.rowHeight = 38;


ticketSheet.showGridLines = false;
ticketSheet.tabColor = mediumGreen;
const ticketHeaders = [
  "Nro", "Grupo ticket", "Fecha", "Lugar normalizado", "Items", "Total", "Filas fuente", "Items a revisar"
];
ticketSheet.getRange("A1:H1").values = [ticketHeaders];
ticketSheet.getRangeByIndexes(1, 0, report.tickets.length, ticketHeaders.length).values = report.tickets.map((ticket) => [
  Number(ticket.ticket_number),
  ticket.ticket_group,
  asDate(ticket.expense_date),
  ticket.place,
  Number(ticket.item_count),
  Number(ticket.ticket_total),
  ticket.source_rows,
  Number(ticket.review_items),
]);
styleHeader(ticketSheet.getRange("A1:H1"));
styleBody(ticketSheet.getRangeByIndexes(1, 0, report.tickets.length, ticketHeaders.length));
ticketSheet.getRangeByIndexes(1, 2, report.tickets.length, 1).setNumberFormat("dd/mm/yyyy");
ticketSheet.getRangeByIndexes(1, 5, report.tickets.length, 1).setNumberFormat('"$"#,##0.00');
const ticketTable = ticketSheet.tables.add(`A1:H${report.tickets.length + 1}`, true, "TicketsPreparados");
ticketTable.style = "TableStyleMedium4";
ticketSheet.freezePanes.freezeRows(1);
ticketSheet.freezePanes.freezeColumns(2);
ticketSheet.getRange("A:A").format.columnWidth = 9;
ticketSheet.getRange("B:B").format.columnWidth = 34;
ticketSheet.getRange("C:C").format.columnWidth = 13;
ticketSheet.getRange("D:D").format.columnWidth = 30;
ticketSheet.getRange("E:F").format.columnWidth = 14;
ticketSheet.getRange("G:G").format.columnWidth = 28;
ticketSheet.getRange("H:H").format.columnWidth = 16;


detailSheet.showGridLines = false;
const detailHeaders = [
  "Fila Excel", "ID origen", "Grupo ticket", "Fecha", "Lugar original", "Lugar normalizado",
  "Motivo original", "Motivo normalizado", "Marca original", "Marca normalizada",
  "Cantidad original", "Cantidad", "Unidad", "Presentacion", "Subtotal", "Precio unitario",
  "Estado", "Observacion"
];
detailSheet.getRange("A1:R1").values = [detailHeaders];
detailSheet.getRangeByIndexes(1, 0, report.rows.length, detailHeaders.length).values = report.rows.map((row) => [
  Number(row.excel_row),
  row.source_id,
  row.ticket_group,
  asDate(row.expense_date),
  row.place_original,
  row.place_normalized,
  row.motive_original,
  row.motive_normalized,
  row.brand_original ?? "",
  row.brand_normalized ?? "",
  row.quantity_original ?? "",
  Number(row.quantity),
  row.unit,
  row.presentation ?? "",
  Number(row.line_total),
  Number(row.unit_price),
  row.status,
  row.note ?? "",
]);
styleHeader(detailSheet.getRange("A1:R1"));
styleBody(detailSheet.getRangeByIndexes(1, 0, report.rows.length, detailHeaders.length));
detailSheet.getRangeByIndexes(1, 3, report.rows.length, 1).setNumberFormat("dd/mm/yyyy");
detailSheet.getRangeByIndexes(1, 11, report.rows.length, 1).setNumberFormat("0.000");
detailSheet.getRangeByIndexes(1, 14, report.rows.length, 2).setNumberFormat('"$"#,##0.00');
detailSheet.getRangeByIndexes(1, 0, report.rows.length, 5).format.fill = lightGray;
detailSheet.getRangeByIndexes(1, 5, report.rows.length, 13).format.fill = "#FFFDF5";
detailSheet.getRangeByIndexes(1, 16, report.rows.length, 1).conditionalFormats.add("containsText", {
  text: "REVISAR",
  format: { fill: amber, font: { color: amberText, bold: true } },
});
const detailTable = detailSheet.tables.add(`A1:R${report.rows.length + 1}`, true, "DetallePreparado");
detailTable.style = "TableStyleMedium4";
detailSheet.freezePanes.freezeRows(1);
detailSheet.freezePanes.freezeColumns(3);
const widths = [10, 12, 35, 13, 30, 30, 28, 28, 22, 22, 20, 12, 12, 22, 16, 16, 12, 52];
widths.forEach((width, index) => {
  detailSheet.getRangeByIndexes(0, index, report.rows.length + 1, 1).format.columnWidth = width;
});


workbook.recalculate();
const summaryInspection = await workbook.inspect({
  kind: "table",
  range: "Resumen!A2:F25",
  include: "values,formulas",
  tableMaxRows: 30,
  tableMaxCols: 8,
});
const errorInspection = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(summaryInspection.ndjson);
console.log(errorInspection.ndjson);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const previewDir = path.join(path.dirname(outputPath), "previews");
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, filename] of [
  ["Resumen", "A1:F27", "resumen.png"],
  ["Tickets", "A1:H25", "tickets.png"],
  ["Detalle importacion", "A1:R18", "detalle.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(path.join(previewDir, filename), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`output: ${outputPath}`);
