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
        const data = sheet.getDataRange().getValues();
        if (data.length < 2) return ContentService.createTextOutput("[]").setMimeType(ContentService.MimeType.JSON);

        const rawHeaders = data[0];
        const headers = rawHeaders.map(h => h.toString().trim().toLowerCase());
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Esnek başlık bulma fonksiyonu
        const findIndex = (opts) => {
            for (let opt of opts) {
                let idx = headers.indexOf(opt.toLowerCase());
                if (idx !== -1) return idx;
            }
            return -1;
        };

        const bitisIdx = findIndex(["Bitiş Tarihi", "bitis tarihi", "Bitiş", "bitis", "End Date", "Expiry"]);
        const telegramIdIdx = findIndex(["Telegram ID", "telegram id", "ID", "id", "User ID"]);
        const durumIdx = findIndex(["Durum", "durum", "Status", "status"]);

        if (bitisIdx === -1 || telegramIdIdx === -1) {
            return ContentService.createTextOutput(JSON.stringify({
                error: "Sütunlar bulunamadı",
                headers_found: headers,
                required: ["Bitiş Tarihi", "Telegram ID"]
            })).setMimeType(ContentService.MimeType.JSON);
        }

        const expired = [];

        for (let i = 1; i < data.length; i++) {
            const row = data[i];
            const bitisVal = row[bitisIdx];
            const telegramId = (row[telegramIdIdx] || "").toString().trim();
            const durum = (row[durumIdx] || "").toString().trim();

            if (!telegramId) continue;

            try {
                let endDate = null;

                if (bitisVal instanceof Date) {
                    endDate = bitisVal;
                } else if (typeof bitisVal === "string" && bitisVal.includes(".")) {
                    const parts = bitisVal.split(".");
                    if (parts.length === 3) {
                        // DD.MM.YYYY formatı
                        endDate = new Date(parts[2], parts[1] - 1, parts[0]);
                    }
                }

                if (endDate && endDate < today) {
                    // Eğer zaten "Süresi Doldu" veya "Pasif" işaretlenmişse tekrar bildirim gitmesin
                    // Ama kullanıcı "yüzlerce var" dediği için şimdilik Aktif olanları veya boş olanları alalım
                    if (durum.includes("Süresi Doldu") || durum.includes("🔴") || durum.includes("Pasif")) {
                        continue;
                    }

                    expired.push({
                        telegram_id: telegramId,
                        bitis_tarihi: bitisVal
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
