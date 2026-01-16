from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.models.boletos import Boleto, CnabRemittance, CnabReturnImport
from app.models.receber import Installment
from app.modules.boletos.service import generate_boletos_for_competence, generate_cnab_remittance, import_cnab_return

router = APIRouter(prefix="/boletos", tags=["boletos"])

@router.get("")
def boletos_page(request: Request, competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    boletos = (
        db.query(Boleto)
        .join(Installment, Installment.id == Boleto.installment_id)
        .filter(Installment.competence_month == competence)
        .order_by(Boleto.id.desc())
        .all()
    )
    remessas = db.query(CnabRemittance).filter(CnabRemittance.competence_month == competence).order_by(CnabRemittance.id.desc()).all()
    retornos = db.query(CnabReturnImport).filter(CnabReturnImport.competence_month == competence).order_by(CnabReturnImport.id.desc()).all()
    return templates.TemplateResponse("boletos/boletos.html", {
        "request": request, "user": user, "competence": competence,
        "boletos": boletos, "remessas": remessas, "retornos": retornos
    })

@router.get("/pdf/{boleto_id}")
def download_boleto_pdf(boleto_id: int, user=Depends(require_login), db: Session = Depends(get_db)):
    b = db.query(Boleto).filter(Boleto.id == boleto_id).first()
    if not b or not b.pdf_path:
        return {"error": "PDF não encontrado"}
    return FileResponse(path=b.pdf_path, filename=f"boleto_{b.id}.pdf", media_type="application/pdf")

@router.post("/api/{competence}/gerar")
def api_gerar_boletos(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    return generate_boletos_for_competence(db, competence)

@router.post("/api/{competence}/cnab/remessa")
def api_gerar_remessa(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    return generate_cnab_remittance(db, competence)

@router.post("/api/{competence}/cnab/retorno")
async def api_importar_retorno(competence: str, file: UploadFile = File(...), user=Depends(require_login), db: Session = Depends(get_db)):
    data = await file.read()
    return import_cnab_return(db, competence, file.filename, data)
