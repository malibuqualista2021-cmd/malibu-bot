/**
 * 🌴 Malibu Google Sheets Webhook v1.2 - ULTRA ROBUST SCAN
 * 
 * Yenilikler:
 * - Çoklu tarih formatı desteği (DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD, vb.)
 * - Otomatik sütun algılama (Daha fazla varyasyon)
 * - Boş satır ve hatalı veri koruması
 */

const SHEET_NAME = "Sayfa1";

function doPost(e) {
    try {
        const data = JSON.parse(e.postData.contents);
        const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
        let sheet = spreadsheet.getSheetByName(SHEET_NAME);

        if (!sheet) {
            sheet = spreadsheet.insertSheet(SHEET_NAME);
        }

        const headers = sheet.getRange(1, 1, 1, 10).getValues()[0];
        if (!headers[0] || headers[0] === "") {
            sheet.getRange(1, 1, 1, 10).setValues([[
                "Tarih", "Telegram ID", "Kullanıcı", "İsim",
                "TXID", "Plan", "TradingView", "Başlangıç", "Bitiş Tarihi", "Durum"
            ]]);
        }

        const newRow = [
            data.tarih || new Date().toLocaleString("tr-TR"),
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
        return ContentService.createTextOutput(JSON.stringify({ success: true, message: "Kayıt eklendi" }))
            .setMimeType(ContentService.MimeType.JSON);

    } catch (error) {
        return ContentService.createTextOutput(JSON.stringify({ error: error.toString() }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}

function doGet(e) {
    const action = e.parameter.action;
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = spreadsheet.getSheetByName(SHEET_NAME);

    if (!sheet) {
        return ContentService.createTextOutput(JSON.stringify({ error: "Sayfa bulunamadı: " + SHEET_NAME }))
            .setMimeType(ContentService.MimeType.JSON);
    }

    if (action === "expired") {
        const fullData = sheet.getDataRange().getValues();
        if (fullData.length < 2) return ContentService.createTextOutput("[]").setMimeType(ContentService.MimeType.JSON);

        const rawHeaders = fullData[0];
        const headers = rawHeaders.map(h => h.toString().trim().toLowerCase());

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // --- SÜTUN BULMA ---
        const findCol = (keys) => {
            for (let key of keys) {
                let idx = headers.indexOf(key.toLowerCase());
                if (idx !== -1) return idx;
            }
            // Kısmi eşleşme denemesi (örn: içinde "Bitiş" geçen sütun)
            for (let i = 0; i < headers.length; i++) {
                for (let key of keys) {
                    if (headers[i].includes(key.toLowerCase())) return i;
                }
            }
            return -1;
        };

        const bitisIdx = findCol(["Bitiş Tarihi", "Bitiş", "End Date", "Expiry", "Expires"]);
        const idIdx = findCol(["Telegram ID", "ID", "User ID", "UID"]);
        const durumIdx = findCol(["Durum", "Status", "State"]);

        if (bitisIdx === -1 || idIdx === -1) {
            return ContentService.createTextOutput(JSON.stringify({
                error: "Gerekli sütunlar (Bitiş Tarihi, Telegram ID) bulunamadı.",
                headers_found: rawHeaders
            })).setMimeType(ContentService.MimeType.JSON);
        }

        const expiredList = [];

        for (let i = 1; i < fullData.length; i++) {
            const row = fullData[i];
            const rawId = row[idIdx];
            const rawDate = row[bitisIdx];
            const status = (row[durumIdx] || "").toString().trim();

            if (!rawId || rawId === "" || rawId.toString().toLowerCase() === "yok") continue;

            let parsedDate = null;

            // --- TARİH AYRIŞTIRMA (GELİŞMİŞ) ---
            if (rawDate instanceof Date) {
                parsedDate = rawDate;
            } else if (typeof rawDate === "string" && rawDate.trim() !== "") {
                const dateStr = rawDate.trim();
                // Desteklenen ayraçlar: . , / -
                const parts = dateStr.split(/[\.\,\/\-]/);

                if (parts.length === 3) {
                    let d, m, y;
                    // Format tahmini: DD.MM.YYYY veya YYYY.MM.DD
                    if (parts[0].length === 4) { // YYYY.MM.DD
                        y = parseInt(parts[0]);
                        m = parseInt(parts[1]) - 1;
                        d = parseInt(parts[2]);
                    } else { // DD.MM.YYYY
                        d = parseInt(parts[0]);
                        m = parseInt(parts[1]) - 1;
                        y = parseInt(parts[2]);
                        if (y < 100) y += 2000; // 26 -> 2026
                    }
                    parsedDate = new Date(y, m, d);
                }
            }

            // Geçerli tarih ve geçmiş mi kontrolü
            if (parsedDate && !isNaN(parsedDate.getTime())) {
                parsedDate.setHours(0, 0, 0, 0);

                if (parsedDate < today) {
                    // Zaten iptal edilmişse geç
                    if (status.includes("🔴") || status.includes("Pasif") || status.includes("Süresi Doldu")) {
                        continue;
                    }

                    expiredList.push({
                        telegram_id: rawId.toString().trim(),
                        bitis_tarihi: rawDate.toString()
                    });
                }
            }
        }

        return ContentService.createTextOutput(JSON.stringify(expiredList))
            .setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "online", version: "1.2" }))
        .setMimeType(ContentService.MimeType.JSON);
}
