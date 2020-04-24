import re

from django.shortcuts import render
from django.http import FileResponse

# Create your views here.
from github.models import Repository,Commit,BINARY_FILE

def file_view(request,repo,commit,file):
    commit = Commit.objects.get(id = commit)

    file_path,ftype = commit.get_file(file)

    if ftype == BINARY_FILE :
        return FileResponse(open(file_path,'rb'),as_attachment=True)
    else:
        with open(file_path,'r') as f:
            file_content = f.read()
        rows = file_content.count("\n") + 1
        return render(request,"github/file_view.html",{'file_content':file_content,"rows":rows})


    
    
    
