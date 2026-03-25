const DEFAULT_HEADERS = [
  "Adresse",
  "\u00d6VMinHB",
  "VeloMinHB",
  "CHF",
  "AnzZimmer",
  "CHF/Zimmer",
  "HouseFlat",
  "Link",
  "BigNoNos",
];

function doPost(e) {
  try {
    const properties = PropertiesService.getScriptProperties();
    const expectedSecret = String(properties.getProperty("WEBHOOK_SECRET") || "");
    const providedSecret = String((e && e.parameter && e.parameter.secret) || "");
    if (expectedSecret && providedSecret !== expectedSecret) {
      return toJson({ok: false, error: "unauthorized"});
    }

    const params = (e && e.parameter) || {};
    const sheetName = String(params.sheet_name || "House Hunter Test").trim();
    const headers = parseJsonArray(params.headers_json, DEFAULT_HEADERS);
    const row = parseJsonArray(params.row_json, []);
    if (!sheetName) {
      return toJson({ok: false, error: "sheet_name is required"});
    }
    if (!row.length) {
      return toJson({ok: false, error: "row_json is required"});
    }

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = spreadsheet.getSheetByName(sheetName);
    if (!sheet) {
      sheet = spreadsheet.insertSheet(sheetName);
    }
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(headers);
    }

    const link = String(row[7] || "");
    if (link && sheet.getLastRow() > 1) {
      const existingLinks = sheet
        .getRange(2, 8, sheet.getLastRow() - 1, 1)
        .getValues()
        .flat()
        .map(String);
      if (existingLinks.indexOf(link) >= 0) {
        return toJson({ok: true, duplicate: true});
      }
    }

    sheet.appendRow(row);
    return toJson({ok: true, duplicate: false});
  } catch (error) {
    return toJson({ok: false, error: String(error)});
  }
}

function parseJsonArray(raw, fallbackValue) {
  if (!raw) {
    return fallbackValue;
  }
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed : fallbackValue;
}

function toJson(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(ContentService.MimeType.JSON);
}
