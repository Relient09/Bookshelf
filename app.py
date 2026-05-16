import os
import csv
import io
import requests
from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# --- Database Config ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/bookshelf'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# --- Models ---

# Many-to-many join table: books <-> shelves
book_shelves = db.Table('book_shelves',
    db.Column('book_id',  db.Integer, db.ForeignKey('books.id'),  primary_key=True),
    db.Column('shelf_id', db.Integer, db.ForeignKey('shelves.id'), primary_key=True),
)


class Shelf(db.Model):
    __tablename__ = 'shelves'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(128), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':         self.id,
            'name':       self.name,
            'book_count': len(self.books),
        }


class Book(db.Model):
    __tablename__ = 'books'
    id           = db.Column(db.Integer, primary_key=True)
    isbn         = db.Column(db.String(20), unique=True, nullable=True)
    title        = db.Column(db.String(512), nullable=False)
    author       = db.Column(db.String(512))
    description  = db.Column(db.Text)
    publisher    = db.Column(db.String(256))
    publish_date = db.Column(db.String(64))
    cover_url    = db.Column(db.String(1024))
    added_at     = db.Column(db.DateTime, default=datetime.utcnow)
    shelves      = db.relationship('Shelf', secondary=book_shelves, backref='books', lazy=True)

    def to_dict(self):
        return {
            'id':           self.id,
            'isbn':         self.isbn,
            'title':        self.title,
            'author':       self.author,
            'description':  self.description,
            'publisher':    self.publisher,
            'publish_date': self.publish_date,
            'cover_url':    self.cover_url,
            'added_at':     self.added_at.isoformat() if self.added_at else None,
            'shelf_ids':    [s.id for s in self.shelves],
            'shelf_names':  [s.name for s in self.shelves],
        }


@app.before_request
def create_tables():
    db.create_all()
    app.before_request_funcs[None].remove(create_tables)


# --- Open Library Helpers ---

def fetch_description(work_key):
    try:
        resp = requests.get(f'https://openlibrary.org{work_key}.json', timeout=10)
        data = resp.json()
        desc = data.get('description', '')
        if isinstance(desc, dict):
            desc = desc.get('value', '')
        return desc or ''
    except Exception:
        return ''


def fetch_by_isbn(isbn):
    isbn = isbn.replace('-', '').replace(' ', '')
    url = f'https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data'
    resp = requests.get(url, timeout=10)
    data = resp.json()
    key = f'ISBN:{isbn}'
    if key not in data:
        return None
    book = data[key]

    cover = None
    if 'cover' in book:
        cover = book['cover'].get('large') or book['cover'].get('medium') or book['cover'].get('small')

    authors     = ', '.join(a['name'] for a in book.get('authors', []))
    publishers  = ', '.join(p['name'] for p in book.get('publishers', []))
    publish_date = book.get('publish_date', '')

    description = ''
    if book.get('excerpts'):
        description = book['excerpts'][0].get('text', '')
    if not description:
        work_key = (book.get('works') or [{}])[0].get('key', '')
        if work_key:
            description = fetch_description(work_key)

    return {
        'isbn': isbn, 'title': book.get('title', ''), 'author': authors,
        'description': description, 'publisher': publishers,
        'publish_date': publish_date, 'cover_url': cover,
    }


def fetch_edition_details(ol_edition_key, partial):
    try:
        resp    = requests.get(f'https://openlibrary.org{ol_edition_key}.json', timeout=10)
        edition = resp.json()

        isbn = partial.get('isbn') or ''
        if not isbn:
            isbns = edition.get('isbn_13') or edition.get('isbn_10') or []
            isbn  = isbns[0] if isbns else ''

        publisher    = partial.get('publisher') or ', '.join(edition.get('publishers', []))
        publish_date = partial.get('publish_date') or edition.get('publish_date', '')

        ed_desc = edition.get('description', '')
        if isinstance(ed_desc, dict):
            ed_desc = ed_desc.get('value', '')
        description = ed_desc or ''

        if not description:
            work_key = (edition.get('works') or [{}])[0].get('key', '')
            if work_key:
                description = fetch_description(work_key)

        partial.update({'isbn': isbn, 'publisher': publisher,
                        'publish_date': publish_date, 'description': description})
    except Exception:
        pass
    return partial


def fetch_by_title(title):
    url = (
        f'https://openlibrary.org/search.json'
        f'?title={requests.utils.quote(title)}'
        f'&limit=5'
        f'&fields=key,title,author_name,isbn,publisher,first_publish_year,cover_i,edition_key'
    )
    resp    = requests.get(url, timeout=10)
    data    = resp.json()
    results = []
    for doc in data.get('docs', []):
        cover_id   = doc.get('cover_i')
        cover_url  = f'https://covers.openlibrary.org/b/id/{cover_id}-L.jpg' if cover_id else None
        isbn       = (doc.get('isbn') or [None])[0]
        ed_keys    = doc.get('edition_key') or []
        ol_edition = f'/books/{ed_keys[0]}' if ed_keys else None

        partial = {
            'isbn': isbn, 'title': doc.get('title', ''),
            'author': ', '.join(doc.get('author_name', [])),
            'description': '',
            'publisher': ', '.join((doc.get('publisher') or [])[:2]),
            'publish_date': str(doc.get('first_publish_year', '')),
            'cover_url': cover_url,
        }
        if ol_edition:
            partial = fetch_edition_details(ol_edition, partial)
        results.append(partial)
    return results


# --- Shelf Routes ---

@app.route('/api/shelves', methods=['GET'])
def list_shelves():
    shelves = Shelf.query.order_by(Shelf.name).all()
    return jsonify([s.to_dict() for s in shelves])


@app.route('/api/shelves', methods=['POST'])
def create_shelf():
    data = request.json
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if Shelf.query.filter_by(name=name).first():
        return jsonify({'error': 'A shelf with that name already exists'}), 409
    shelf = Shelf(name=name)
    db.session.add(shelf)
    db.session.commit()
    return jsonify(shelf.to_dict()), 201


@app.route('/api/shelves/<int:shelf_id>', methods=['DELETE'])
def delete_shelf(shelf_id):
    shelf = Shelf.query.get_or_404(shelf_id)
    db.session.delete(shelf)
    db.session.commit()
    return jsonify({'deleted': True})


@app.route('/api/books/<int:book_id>/shelves', methods=['POST'])
def add_book_to_shelf(book_id):
    book     = Book.query.get_or_404(book_id)
    shelf_id = (request.json or {}).get('shelf_id')
    shelf    = Shelf.query.get_or_404(shelf_id)
    if shelf not in book.shelves:
        book.shelves.append(shelf)
        db.session.commit()
    return jsonify(book.to_dict())


@app.route('/api/books/<int:book_id>/shelves/<int:shelf_id>', methods=['DELETE'])
def remove_book_from_shelf(book_id, shelf_id):
    book  = Book.query.get_or_404(book_id)
    shelf = Shelf.query.get_or_404(shelf_id)
    if shelf in book.shelves:
        book.shelves.remove(shelf)
        db.session.commit()
    return jsonify(book.to_dict())


# --- Book Routes ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/lookup/isbn', methods=['GET'])
def lookup_isbn():
    isbn = request.args.get('isbn', '').strip()
    if not isbn:
        return jsonify({'error': 'ISBN required'}), 400
    result = fetch_by_isbn(isbn)
    if not result:
        return jsonify({'error': 'Book not found'}), 404
    return jsonify(result)


@app.route('/api/lookup/title', methods=['GET'])
def lookup_title():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Title required'}), 400
    results = fetch_by_title(title)
    if not results:
        return jsonify({'error': 'No books found'}), 404
    return jsonify(results)


@app.route('/api/books', methods=['GET'])
def list_books():
    q        = request.args.get('q', '').strip()
    shelf_id = request.args.get('shelf_id', '').strip()
    query    = Book.query

    if shelf_id:
        query = query.filter(Book.shelves.any(Shelf.id == int(shelf_id)))
    if q:
        like  = f'%{q}%'
        query = query.filter(
            db.or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
        )
    books = query.order_by(Book.added_at.desc()).all()
    return jsonify([b.to_dict() for b in books])


@app.route('/api/books', methods=['POST'])
def add_book():
    data = request.json
    if not data or not data.get('title'):
        return jsonify({'error': 'Title is required'}), 400

    if data.get('isbn'):
        existing = Book.query.filter_by(isbn=data['isbn']).first()
        if existing:
            return jsonify({'error': 'A book with this ISBN already exists', 'existing': existing.to_dict()}), 409

    book = Book(
        isbn=data.get('isbn'), title=data.get('title'), author=data.get('author'),
        description=data.get('description'), publisher=data.get('publisher'),
        publish_date=data.get('publish_date'), cover_url=data.get('cover_url'),
    )

    # Add to shelf if one was provided
    shelf_id = data.get('shelf_id')
    if shelf_id:
        shelf = Shelf.query.get(shelf_id)
        if shelf:
            book.shelves.append(shelf)

    db.session.add(book)
    db.session.commit()
    return jsonify(book.to_dict()), 201


@app.route('/api/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    return jsonify({'deleted': True})


@app.route('/api/books/export', methods=['GET'])
def export_csv():
    books  = Book.query.order_by(Book.added_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'ISBN', 'Title', 'Author', 'Publisher', 'Publish Date', 'Description', 'Shelves', 'Added At'])
    for b in books:
        writer.writerow([b.id, b.isbn, b.title, b.author, b.publisher,
                         b.publish_date, b.description,
                         ', '.join(s.name for s in b.shelves), b.added_at])
    output.seek(0)
    return send_file(
        io.BytesIO(output.read().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='bookshelf.csv'
    )


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
