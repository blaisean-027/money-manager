import google.generativeai as gemini
import json

#영수증 이미지 받아서 데이터 보내는 class
class Analyzer :
    def __init__(self, api):
        gemini.configure(api_key=api)
        self.model = gemini.GenerativeModel('gemini-1.5-flash')
    
    def analyze(self, img):
        prompt = """
        영수증 이미지에서 다음 정보를 추출해 JSON으로 응답해줘.
        JSON 키: store_name, items, total_amount, receipt_date(YYYY-MM-DD)
        items는 품목들을 쉼표로 연결한 문자열로 만들어줘.
        """

        img_data = img.getvalue()
        
        response = self.model.generate_content([
            prompt,
            {'mime_type': 'image/jpeg', 'data': img_data}
        ])

        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
