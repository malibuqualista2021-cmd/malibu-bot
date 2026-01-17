/**
 * 🌴 Malibu Google Sheets Webhook
 * 
 * Bu scripti Google Sheets'e ekleyin:
 * 1. Google Sheets'i açın
 * 2. Extensions → Apps Script
 * 3. Bu kodu yapıştırın
 * 4. Deploy → New deployment → Web app
 * 5. Execute as: Me, Who has access: Anyone
 * 6. URL'yi kopyalayıp SHEETS_WEBHOOK olarak kullanın
 */

// Aktif sayfa
const SHEET_NAME = "Sayfa1";

function doPost(e) {
    try {
        const data = JSON.parse(e.postData.contents);
        const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);

        if (!sheet) {
            return ContentService.createTextOutput(JSON.stringify({ error: "Sheet not found" }))
                .setMimeType(ContentService.MimeType.JSON);
        }

        // Başlık kontrolü
        const headers = sheet.getRange(1, 1, 1, 10).getValues()[0];
        if (!headers[0] || headers[0] === "") {
            sheet.getRange(1, 1, 1, 10).setValues([[
                "Tarih", "Telegram ID", "Telegram Kullanıcı", "İsim",
                "TXID", "Plan", "TradingView", "Başlangıç", "Bitiş", "Durum"
            ]]);
        }

        // Yeni satır ekle
        const newRow = [
            data.tarih || "",
            data.telegram_id || "",
            data.telegram_username || "",
            data.telegram_name || "",
            data.txid || "",
            data.plan || "",
            data.tradingview || "",
            data.baslangic_tarihi || "",
            data.bitis_tarihi || "",
            data.durum || "Beklemede 🟡"
        ];

        sheet.appendRow(newRow);

        // Durum hücresini renklendir
        const lastRow = sheet.getLastRow();
        const statusCell = sheet.getRange(lastRow, 10);
        const status = data.durum || "";

        if (status.includes("Aktif") || status.includes("✅")) {
            statusCell.setBackground("#c6efce");
        } else if (status.includes("Red") || status.includes("❌")) {
            statusCell.setBackground("#ffc7ce");
        } else {
            statusCell.setBackground("#ffeb9c");
        }

        return ContentService.createTextOutput(JSON.stringify({ success: true }))
            .setMimeType(ContentService.MimeType.JSON);

    } catch (error) {
        return ContentService.createTextOutput(JSON.stringify({ error: error.toString() }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}

function doGet(e) {
    const action = e.parameter.action;
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);

    if (!sheet) {
        return ContentService.createTextOutput(JSON.stringify({ error: "Sheet not found" }))
            .setMimeType(ContentService.MimeType.JSON);
    }

    if (action === "expired") {
        // Süresi dolan kullanıcıları bul
        const data = sheet.getDataRange().getValues();
        const headers = data[0];
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const bitisIdx = headers.indexOf("Bitiş");
        const telegramIdIdx = headers.indexOf("Telegram ID");
        const durumIdx = headers.indexOf("Durum");

        const expired = [];

        for (let i = 1; i < data.length; i++) {
            const row = data[i];
            const bitisTarih = row[bitisIdx];
            const durum = row[durumIdx] || "";

            // Aktif olanları kontrol et
            if (!durum.includes("Aktif") && !durum.includes("✅")) continue;

            try {
                let endDate;
                if (typeof bitisTarih === "object") {
                    endDate = bitisTarih;
                } else {
                    const parts = bitisTarih.split(".");
                    endDate = new Date(parts[2], parts[1] - 1, parts[0]);
                }

                if (endDate < today) {
                    expired.push({
                        telegram_id: row[telegramIdIdx],
                        bitis_tarihi: bitisTarih
                    });
                }
            } catch (e) {
                // Tarih parse hatası - atla
            }
        }

        return ContentService.createTextOutput(JSON.stringify(expired))
            .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "ok" }))
        .setMimeType(ContentService.MimeType.JSON);
}
