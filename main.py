from fastapi import FastAPI, Request, File, UploadFile, Form, Response, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
import json
import uvicorn
import zipfile
import io
import base64
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
import tempfile
import os
import requests
from PyPDF2 import PdfReader, PdfWriter
from urllib.parse import unquote # <-- MODIFICA: Import aggiunto

app = FastAPI(title="PDF Generator API", version="1.1.0")

# Modello Pydantic opzionale per validare i dati in input
class PDFRequest(BaseModel):
    titolo: Optional[str] = None
    contenuto: Optional[str] = None
    parametri: Optional[Dict[str, Any]] = None

def download_logo() -> Optional[bytes]:
    """
    Scarica il logo da URL e lo restituisce come bytes.
    """
    logo_url = "https://automatikoagency.github.io/dpsonline_genera_pdf/aster_logo.png"
    try:
        print(f"Scaricando logo da: {logo_url}")
        response = requests.get(logo_url, timeout=10)
        response.raise_for_status()
        print(f"Logo scaricato con successo: {len(response.content)} bytes")
        return response.content
    except Exception as e:
        print(f"ERRORE nel download del logo: {e}")
        return None

def create_pdf_from_images(zip_binary_data: bytes) -> bytes:
    """
    Crea un PDF dalle immagini contenute nel file ZIP.
    Ogni immagine diventa una pagina del PDF.
    """
    pdf_buffer = io.BytesIO()
    
    # Scarica il logo una sola volta
    logo_bytes = download_logo()
    logo_image = None
    if logo_bytes:
        try:
            logo_image = Image.open(io.BytesIO(logo_bytes))
            # Converti in RGB se necessario
            if logo_image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', logo_image.size, (255, 255, 255))
                if logo_image.mode == 'P':
                    logo_image = logo_image.convert('RGBA')
                background.paste(logo_image, mask=logo_image.split()[-1] if logo_image.mode in ('RGBA', 'LA') else None)
                logo_image = background
            elif logo_image.mode != 'RGB':
                logo_image = logo_image.convert('RGB')
            print("Logo preparato con successo")
        except Exception as e:
            print(f"Errore nella preparazione del logo: {e}")
            logo_image = None
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_binary_data), 'r') as zip_ref:
            # Crea il PDF
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            page_width, page_height = A4
            
            # Lista tutti i file nel ZIP
            file_list = zip_ref.namelist()
            print(f"\nCreazione PDF: trovati {len(file_list)} file nel ZIP")
            
            # Filtra solo i file immagine (per sicurezza)
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
            image_files = []
            
            for filename in file_list:
                is_image = any(filename.lower().endswith(ext) for ext in image_extensions)
                if not is_image:
                    try:
                        file_data = zip_ref.read(filename)
                        Image.open(io.BytesIO(file_data))
                        is_image = True
                        print(f"File {filename} riconosciuto come immagine (senza estensione)")
                    except:
                        print(f"File {filename} saltato: non è un'immagine")
                        continue
                
                if is_image:
                    image_files.append(filename)
            
            print(f"File immagine trovati: {image_files}")
            
            if not image_files:
                print("ERRORE: Nessuna immagine trovata nel ZIP!")
                c.drawString(100, 750, "Nessuna immagine trovata nel file ZIP")
                c.showPage()
            else:
                # PRIMA PAGINA: COPERTINA CON LOGO E TITOLO
                print("Creazione pagina di copertina...")
                
                if logo_image:
                    try:
                        logo_buffer = io.BytesIO()
                        logo_image.save(logo_buffer, format='PNG')
                        logo_buffer.seek(0)
                        
                        cover_logo_width_px = 180
                        cover_logo_width_pt = cover_logo_width_px * 0.75
                        logo_original_width, logo_original_height = logo_image.size
                        cover_logo_height_pt = (logo_original_height / logo_original_width) * cover_logo_width_pt
                        
                        logo_x = (page_width - cover_logo_width_pt) / 2
                        logo_y = page_height * 0.75
                        
                        c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, cover_logo_width_pt, cover_logo_height_pt)
                        print(f"Logo copertina aggiunto ({cover_logo_width_pt:.0f}x{cover_logo_height_pt:.0f} pt)")
                    except Exception as e:
                        print(f"Errore logo copertina: {e}")
                
                margin = 50
                max_text_width = page_width - 2 * margin
                
                title_text = "SELEZIONE STAMPA"
                font_size = 50
                while font_size > 10:
                    title_width = c.stringWidth(title_text, "Helvetica-Bold", font_size)
                    if title_width <= max_text_width:
                        break
                    font_size -= 1
                
                c.setFont("Helvetica-Bold", font_size)
                title_width = c.stringWidth(title_text, "Helvetica-Bold", font_size)
                title_x = (page_width - title_width) / 2
                title_y = page_height * 0.55
                c.drawString(title_x, title_y, title_text)
                
                today = datetime.now()
                months = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                          "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
                date_text = f"{today.day} {months[today.month-1]} {today.year}"
                
                c.setFont("Helvetica-Bold", font_size)
                date_width = c.stringWidth(date_text, "Helvetica-Bold", font_size)
                date_x = (page_width - date_width) / 2
                date_y = title_y - 70
                c.drawString(date_x, date_y, date_text)
                
                print(f"Copertina creata: {title_text} (font {font_size}pt) - {date_text} (font {font_size}pt)")
                
                c.showPage()
                
                image_files.sort()
                
                for i, filename in enumerate(image_files):
                    print(f"Elaborando immagine {i+1}/{len(image_files)}: {filename}")
                    
                    try:
                        image_data = zip_ref.read(filename)
                        
                        with Image.open(io.BytesIO(image_data)) as img:
                            if img.mode in ('RGBA', 'LA', 'P'):
                                background = Image.new('RGB', img.size, (255, 255, 255))
                                if img.mode == 'P':
                                    img = img.convert('RGBA')
                                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                                img = background
                            elif img.mode != 'RGB':
                                img = img.convert('RGB')
                            
                            img_buffer = io.BytesIO()
                            if filename.lower().endswith(('.png', '.gif', '.bmp', '.tiff')):
                                img.save(img_buffer, format='PNG')
                            else:
                                img.save(img_buffer, format='JPEG', quality=100)
                            img_buffer.seek(0)
                            
                            img_width, img_height = img.size
                            
                            logo_space_height = 0
                            if logo_image:
                                logo_width_px = 120
                                logo_width_pt = logo_width_px * 0.75
                                logo_original_width, logo_original_height = logo_image.size
                                logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt
                                logo_space_height = logo_height_pt + 1
                            
                            margin = 50
                            margin_top = margin + logo_space_height
                            max_width = page_width - 2 * margin
                            max_height = page_height - margin - margin_top
                            
                            scale_x = max_width / img_width
                            scale_y = max_height / img_height
                            scale = min(scale_x, scale_y)
                            
                            scaled_width = img_width * scale
                            scaled_height = img_height * scale
                            
                            x = (page_width - scaled_width) / 2
                            y = (page_height - margin_top - scaled_height) / 2
                            
                            c.drawImage(ImageReader(img_buffer), x, y, scaled_width, scaled_height)
                            
                            if logo_image:
                                try:
                                    logo_buffer = io.BytesIO()
                                    logo_image.save(logo_buffer, format='PNG')
                                    logo_buffer.seek(0)
                                    
                                    logo_width_px = 120
                                    logo_width_pt = logo_width_px * 0.75
                                    logo_original_width, logo_original_height = logo_image.size
                                    logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt
                                    
                                    logo_x = margin
                                    logo_y = page_height - margin - logo_height_pt
                                    
                                    c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, logo_width_pt, logo_height_pt)
                                    
                                    print(f"Logo aggiunto alla pagina {i+1} ({logo_width_pt:.0f}x{logo_height_pt:.0f} pt)")
                                except Exception as e:
                                    print(f"Errore nell'aggiunta del logo alla pagina {i+1}: {e}")
                            
                            print(f"Immagine {filename} aggiunta al PDF ({img_width}x{img_height} -> {scaled_width:.0f}x{scaled_height:.0f})")
                    
                    except Exception as e:
                        print(f"ERRORE nell'elaborazione di {filename}: {e}")
                        c.drawString(100, 400, f"Errore nel caricare l'immagine: {filename}")
                        c.drawString(100, 380, f"Errore: {str(e)}")
                    
                    if i < len(image_files) - 1:
                        c.showPage()
            
            c.save()
            
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()
        print(f"PDF creato con successo! Dimensione: {len(pdf_bytes)} bytes")
        return pdf_bytes
        
    except Exception as e:
        print(f"ERRORE nella creazione del PDF: {e}")
        error_pdf = io.BytesIO()
        c = canvas.Canvas(error_pdf, pagesize=A4)
        c.drawString(100, 750, f"Errore nella creazione del PDF:")
        c.drawString(100, 730, str(e))
        c.save()
        error_pdf.seek(0)
        return error_pdf.getvalue()

def add_screenshot_to_pdf(pdf_bytes: bytes, link: str) -> bytes:
    """
    Aggiunge una pagina con screenshot del link al PDF esistente.
    Il link viene decodificato e reso cliccabile.
    """
    try:
        # MODIFICA: Decodifica il link da formato URI a URL standard
        decoded_link = unquote(link)
        print(f"Link ricevuto: {link}")
        print(f"Link decodificato: {decoded_link}")

        # Scarica il logo
        logo_bytes = download_logo()
        logo_image = None
        if logo_bytes:
            try:
                logo_image = Image.open(io.BytesIO(logo_bytes))
                if logo_image.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', logo_image.size, (255, 255, 255))
                    if logo_image.mode == 'P':
                        logo_image = logo_image.convert('RGBA')
                    background.paste(logo_image, mask=logo_image.split()[-1] if logo_image.mode in ('RGBA', 'LA') else None)
                    logo_image = background
                elif logo_image.mode != 'RGB':
                    logo_image = logo_image.convert('RGB')
            except Exception as e:
                print(f"Errore nella preparazione del logo: {e}")
                logo_image = None
        
        # Cattura screenshot del sito
        screenshot_url = f"https://api.pikwy.com/?token=d2da7ac0dc62e0830b9a6e020c199be3101072af0ad3a6a6&url={decoded_link}&width=960&height=1300&delay=6000"
        print(f"Catturando screenshot da: {decoded_link}")
        
        screenshot_response = requests.get(screenshot_url, timeout=60)
        screenshot_response.raise_for_status()
        screenshot_bytes = screenshot_response.content
        print(f"Screenshot catturato: {len(screenshot_bytes)} bytes")
        
        screenshot_image = Image.open(io.BytesIO(screenshot_bytes))
        if screenshot_image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', screenshot_image.size, (255, 255, 255))
            if screenshot_image.mode == 'P':
                screenshot_image = screenshot_image.convert('RGBA')
            background.paste(screenshot_image, mask=screenshot_image.split()[-1] if screenshot_image.mode in ('RGBA', 'LA') else None)
            screenshot_image = background
        elif screenshot_image.mode != 'RGB':
            screenshot_image = screenshot_image.convert('RGB')
        
        # Crea una nuova pagina PDF con lo screenshot
        new_page_buffer = io.BytesIO()
        c = canvas.Canvas(new_page_buffer, pagesize=A4)
        page_width, page_height = A4
        
        img_width, img_height = screenshot_image.size
        
        logo_space_height = 0
        link_space_height = 2
        
        if logo_image:
            logo_width_px = 120
            logo_width_pt = logo_width_px * 0.75
            logo_original_width, logo_original_height = logo_image.size
            logo_height_pt = (logo_original_height / logo_original_width) * logo_width_pt
            logo_space_height = logo_height_pt + 15
        
        margin = 50
        margin_top = margin + logo_space_height
        margin_bottom = margin + link_space_height
        max_width = page_width - 2 * margin
        max_height = page_height - margin_top - margin_bottom
        
        scale_x = max_width / img_width
        scale_y = max_height / img_height
        scale = min(scale_x, scale_y)
        
        scaled_width = img_width * scale
        scaled_height = img_height * scale
        
        x = (page_width - scaled_width) / 2
        y = margin_bottom + (max_height - scaled_height) / 2
        
        screenshot_buffer = io.BytesIO()
        screenshot_image.save(screenshot_buffer, format='PNG')
        screenshot_buffer.seek(0)
        
        c.drawImage(ImageReader(screenshot_buffer), x, y, scaled_width, scaled_height)
        
        if logo_image:
            try:
                logo_buffer = io.BytesIO()
                logo_image.save(logo_buffer, format='PNG')
                logo_buffer.seek(0)
                
                logo_x = margin
                logo_y = page_height - margin - logo_height_pt
                
                c.drawImage(ImageReader(logo_buffer), logo_x, logo_y, logo_width_pt, logo_height_pt)
                print("Logo aggiunto alla pagina screenshot")
            except Exception as e:
                print(f"Errore nell'aggiunta del logo: {e}")
        
        # --- SEZIONE MODIFICATA PER IL LINK CLICCABILE ---
        
        font_name = "Helvetica"
        font_size = 10
        link_text = decoded_link
        
        c.setFont(font_name, font_size)
        
        link_width = c.stringWidth(link_text, font_name, font_size)
        link_x = (page_width - link_width) / 2
        link_y = margin / 2
        
        # Disegna il testo in blu per farlo sembrare un link
        c.setFillColorRGB(0, 0, 1)
        c.drawString(link_x, link_y, link_text)
        
        # Crea l'area cliccabile (hotspot)
        rect = [link_x, link_y, link_x + link_width, link_y + font_size]
        c.linkURL(decoded_link, rect, relative=1)
        
        print(f"Link cliccabile aggiunto: {decoded_link}")
        
        # --- FINE SEZIONE MODIFICATA ---
        
        c.save()
        new_page_buffer.seek(0)
        
        # Combina il PDF esistente con la nuova pagina
        existing_pdf = PdfReader(io.BytesIO(pdf_bytes))
        new_page_pdf = PdfReader(new_page_buffer)
        
        writer = PdfWriter()
        
        for page in existing_pdf.pages:
            writer.add_page(page)
        
        writer.add_page(new_page_pdf.pages[0])
        
        final_pdf_buffer = io.BytesIO()
        writer.write(final_pdf_buffer)
        final_pdf_buffer.seek(0)
        
        final_pdf_bytes = final_pdf_buffer.getvalue()
        print(f"PDF finale creato con {len(existing_pdf.pages) + 1} pagine, dimensione: {len(final_pdf_bytes)} bytes")
        
        return final_pdf_bytes
        
    except Exception as e:
        print(f"ERRORE nell'aggiunta dello screenshot per il link {link}: {e}")
        # Restituisce il PDF originale in caso di errore
        return pdf_bytes

@app.post("/genera_pdf")
async def genera_pdf(
    request: Request,
    file: Optional[UploadFile] = File(None),
    zip_data: Optional[str] = Form(None),
    link: Optional[str] = Header(None)
):
    """
    Endpoint POST per generare PDF.
    1. Riceve un file ZIP di immagini (da file, form data base64, o raw body).
    2. Crea un PDF con una copertina e una pagina per ogni immagine.
    3. Se l'header 'link' è presente, aggiunge una pagina di screenshot per ogni URL.
    """
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"NUOVA RICHIESTA GENERA_PDF - {timestamp}")
    print("=" * 60)
    
    print("\n--- HEADERS ---")
    for header_name, header_value in request.headers.items():
        print(f"{header_name}: {header_value}")
    
    # Gestione FILE ZIP UPLOAD
    zip_binary_data = None
    if file:
        print("\n--- FILE UPLOAD ---")
        print(f"Nome file: {file.filename}")
        zip_binary_data = await file.read()
    
    # Gestione ZIP DATA in base64
    elif zip_data:
        print("\n--- ZIP DATA BASE64 ---")
        try:
            zip_binary_data = base64.b64decode(zip_data)
        except Exception as e:
            print(f"Errore nella decodifica base64: {e}")
    
    # Gestione raw body
    else:
        body = await request.body()
        if body:
            print("\n--- RAW BODY ---")
            if body.startswith(b'PK'): # Magic number per ZIP
                print("Body sembra essere un file ZIP!")
                zip_binary_data = body
            else:
                print("Body non è un file ZIP, ignorato.")


    print("=" * 60)
    print("INIZIO ELABORAZIONE")
    print("=" * 60)
    
    if not zip_binary_data:
        return Response(
            content=json.dumps({
                "status": "error",
                "message": "Nessun file ZIP valido ricevuto (controllare file upload, form 'zip_data' o raw body)",
                "timestamp": timestamp
            }),
            status_code=400,
            media_type="application/json"
        )
        
    # 1. CREAZIONE DEL PDF DALLE IMMAGINI
    print("\n" + "=" * 20 + " FASE 1: CREAZIONE PDF DA IMMAGINI " + "=" * 20)
    pdf_bytes = create_pdf_from_images(zip_binary_data)
    
    # 2. AGGIUNTA SCREENSHOT SE IL LINK È PRESENTE
    if link:
        print("\n" + "=" * 20 + " FASE 2: AGGIUNTA SCREENSHOT " + "="*20)
        # Pulisci e splitta i link, gestendo spazi e virgole multiple
        links = [url.strip() for url in link.split(',') if url.strip()]
        print(f"Trovati {len(links)} link nell'header: {links}")
        
        for i, single_link in enumerate(links):
            print(f"\n--- Elaborazione link {i+1}/{len(links)}: {single_link} ---")
            pdf_bytes = add_screenshot_to_pdf(pdf_bytes, single_link)
        
        print("\n" + "="*20 + " FINE AGGIUNTA SCREENSHOT " + "="*20)

    else:
        print("\nNessun header 'link' trovato. Salto l'aggiunta di screenshot.")

    # 3. Restituisci il PDF finale (originale o modificato)
    print("\n" + "="*20 + " INVIO RISPOSTA PDF " + "="*20)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report_{timestamp.replace(' ', '_').replace(':', '-')}.pdf"
        }
    )

@app.get("/")
async def root():
    """Endpoint di test per verificare che l'API funzioni"""
    return {"message": "FastAPI PDF Generator è attivo!"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    print("Avvio del server FastAPI...")
    print("Installare le dipendenze con:")
    print("pip install fastapi uvicorn pillow reportlab requests PyPDF2")
    print("\nServer disponibile su http://0.0.0.0:8000")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=True
    )
