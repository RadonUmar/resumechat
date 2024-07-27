import os
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Message
from .serializers import MessageSerializer
import google.generativeai as genai
import PyPDF2
from django.shortcuts import render

def chat_view(request):
    return render(request, 'chat/index.html')

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer

    @action(detail=False, methods=['POST'])
    def chat(self, request):
        user_message = request.data.get('message', '')
        
        # Save user message
        Message.objects.create(content=user_message, is_bot=False)

        # Configure the Gemini API
        genai.configure(api_key=settings.GEMINI_API_KEY)

        # Generate a response using the Gemini API
        model = genai.GenerativeModel('gemini-1.0-pro')
        response = model.generate_content(user_message)

        bot_response = response.text

        # Save bot message
        bot_message = Message.objects.create(content=bot_response, is_bot=True)

        return Response(MessageSerializer(bot_message).data)

    @action(detail=False, methods=['POST'])
    def review_resume(self, request):
        pdf_file = request.FILES.get('pdf')
        custom_prompt = request.data.get('prompt', 'Review this resume and provide feedback.')

        if not pdf_file:
            return Response({'error': 'No PDF file uploaded'}, status=400)

        # Save the PDF file temporarily
        file_name = default_storage.save('tmp/resume.pdf', ContentFile(pdf_file.read()))
        file_path = os.path.join(settings.MEDIA_ROOT, file_name)

        try:
            # Extract text from PDF
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ''
                for page in pdf_reader.pages:
                    text += page.extract_text()

            # Configure the Gemini API
            genai.configure(api_key=settings.GEMINI_API_KEY)

            # Initialize the model
            model = genai.GenerativeModel('gemini-1.0-pro')

            # Split the text into chunks if it's too long
            max_chunk_size = 7000  # Adjust this value based on Gemini's token limit
            chunks = [text[i:i+max_chunk_size] for i in range(0, len(text), max_chunk_size)]

            feedback = ""
            for i, chunk in enumerate(chunks):
                chunk_prompt = f"{custom_prompt}\n\nResume content (Part {i+1}/{len(chunks)}):\n{chunk}"
                response = model.generate_content(chunk_prompt)
                feedback += response.text + "\n\n"

            # If there were multiple chunks, summarize the feedback
            if len(chunks) > 1:
                summary_prompt = f"Summarize the following resume feedback:\n\n{feedback}"
                summary_response = model.generate_content(summary_prompt)
                feedback = summary_response.text

            # Save bot message
            bot_message = Message.objects.create(content=feedback, is_bot=True)

            return Response(MessageSerializer(bot_message).data)

        except Exception as e:
            return Response({'error': str(e)}, status=500)

        finally:
            # Clean up the temporary file
            default_storage.delete(file_name)