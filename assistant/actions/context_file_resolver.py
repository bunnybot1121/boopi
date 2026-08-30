import os
import time
import glob
from logger import log

class ContextFileResolver:
  def __init__(self, workspace_path="c:\\Users\\Sachin\\hackathon"):
    self.workspace_path = workspace_path
    self.search_dirs = [
      os.path.expanduser("~/Desktop"),
      os.path.expanduser("~/Documents"),
      os.path.expanduser("~/Downloads"),
      workspace_path
    ]

  def resolve_path(self, query: str, resolve_type: str = None) -> tuple:
    """Finds the most relevant file or folder matching the query.
    resolve_type can be "file", "dir", or None.
    Returns (best_match_path, is_directory, score) or (None, False, 0)
    """
    log.info(f"ContextFileResolver resolving path for query: '{query}' (type={resolve_type})")
    query_lower = query.lower().strip()
    
    # Strip code: prefix if present in query
    if query_lower.startswith("code:"):
      query_lower = query_lower[5:].strip()
      
    # Extract search terms by splitting on spaces, colons, underscores, hyphens
    import re
    words = re.split(r'[_\-\s:]+', query_lower)
    fillers = ["open", "my", "latest", "file", "folder", "documents", "document", "the", "a", "an", "please", "show", "get"]
    keywords = [word for word in words if word not in fillers and len(word) > 1]
    
    # If keywords are empty, fallback to the split query words
    if not keywords:
      keywords = [word for word in words if len(word) > 1]
      
    if not keywords:
      return None, False, 0
      
    log.info(f"Extracted search keywords for resolving: {keywords}")
    
    candidates = []
    
    # Map file categories to extensions
    doc_extensions = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".md"]
    is_presentation = "presentation" in query_lower or "ppt" in query_lower or "slides" in query_lower
    is_report = "report" in query_lower or "doc" in query_lower
    is_code = "code" in query_lower or "project" in query_lower
    
    now = time.time()
    
    # Scan standard directories (limit depth to 3 levels to maintain performance)
    for base_dir in self.search_dirs:
      if not os.path.exists(base_dir):
        continue
        
      # Score the base directory itself! (only if resolve_type != "file")
      if resolve_type != "file":
        base_dir_name = os.path.basename(os.path.abspath(base_dir)).lower()
        score = 0
        for kw in keywords:
          if kw in base_dir_name:
            score += 50
        if score > 0:
          candidates.append((base_dir, score, True))
      
      # Traverse folders
      for root, dirs, files in os.walk(base_dir):
        # Limit depth
        depth = root[len(base_dir):].count(os.sep)
        if depth > 2:
          dirs.clear() # don't go deeper
          continue
          
        # 1. Score matching folders (only if resolve_type != "file")
        if resolve_type != "file":
          for d in dirs:
            folder_path = os.path.join(root, d)
            folder_name_lower = d.lower()
            
            # Score folder based on keyword match
            score = 0
            for kw in keywords:
              if kw in folder_name_lower:
                score += 50
                
            if score > 0:
              try:
                mtime = os.path.getmtime(folder_path)
                recency_days = (now - mtime) / (24 * 3600)
                if recency_days <= 1:
                  score += 30
                elif recency_days <= 7:
                  score += 15
                elif recency_days <= 30:
                  score += 5
              except Exception:
                pass
              
              # Boost if query wanted a project/folder
              if is_code:
                score += 20
                
              candidates.append((folder_path, score, True)) # Path, score, is_directory
            
        # 2. Score matching files (only if resolve_type != "dir")
        if resolve_type != "dir":
          for f in files:
            file_path = os.path.join(root, f)
            filename_lower = f.lower()
            name_part, ext = os.path.splitext(filename_lower)
            
            score = 0
            # Skip hidden/temporary files
            if f.startswith("~") or f.startswith("."):
              continue
              
            for kw in keywords:
              if kw in name_part:
                score += 50
                
            if score > 0:
              try:
                mtime = os.path.getmtime(file_path)
                recency_days = (now - mtime) / (24 * 3600)
                if recency_days <= 1:
                  score += 30
                elif recency_days <= 7:
                  score += 15
                elif recency_days <= 30:
                  score += 5
              except Exception:
                pass
                
              # Category boost
              if is_presentation and ext in [".pptx", ".ppt"]:
                score += 30
              elif is_report and ext in [".docx", ".doc", ".pdf"]:
                score += 20
              elif ext in doc_extensions:
                score += 5 # generic doc boost
                
              candidates.append((file_path, score, False))
            
    # Special fallback: if query implies the main project/workspace and no high-score match is found
    # (only if resolve_type != "file")
    if resolve_type != "file":
      if not candidates or max(c[1] for c in candidates) < 40:
        if any(x in query_lower for x in ["project", "code", "bupi", "hackathon"]):
          candidates.append((self.workspace_path, 50, True))
        
    if not candidates:
      return None, False, 0
      
    # Sort candidates by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_match, best_score, is_dir = candidates[0]
    return best_match, is_dir, best_score

  def resolve_and_open(self, query: str) -> str:
    """Finds the most relevant file or folder matching the query and opens it."""
    log.info(f"ContextFileResolver resolving query: '{query}'")
    
    # Check if query starts with code: prefix (so we know if we need code editor)
    is_code = query.lower().strip().startswith("code:")
    
    best_match, is_dir, best_score = self.resolve_path(query)
    
    if not best_match:
      return "No matching files or folders found."
      
    log.info(f"Best match: '{best_match}' with score {best_score}")
    
    if best_score < 40:
      return f"I found a possible match at '{best_match}', but I wasn't confident enough to open it (score: {best_score})."
      
    try:
      if is_code:
        import subprocess
        if os.name == 'nt':
          subprocess.Popen(["cmd", "/c", f"code \"{best_match}\""], shell=True)
        else:
          subprocess.Popen(["code", best_match])
        basename = os.path.basename(best_match)
        type_name = "folder" if is_dir else "file"
        return f"Successfully opened the {type_name} '{basename}' at '{best_match}' in VS Code."
      else:
        os.startfile(best_match)
        basename = os.path.basename(best_match)
        type_name = "folder" if is_dir else "file"
        return f"Successfully opened the {type_name} '{basename}' at '{best_match}'."
    except Exception as e:
      log.error(f"Failed to open resolved target: {e}")
      return f"I found the best match at '{best_match}', but encountered an error opening it: {e}"
